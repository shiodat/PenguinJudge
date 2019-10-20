import asyncio
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
from functools import partial
from typing import Any
import pickle

import pika  # type: ignore
from pika.channel import Channel  # type: ignore
from pika.exceptions import AMQPError  # type: ignore
from pika.adapters.asyncio_connection import AsyncioConnection  # type: ignore

from penguin_judge.models import (
    Environment, Problem, Submission, JudgeStatus, JudgeResult, TestCase,
    transaction)
from penguin_judge.mq import get_mq_conn_params
from penguin_judge.run_container import run


class Worker(object):
    def __init__(self, db_config: dict, max_processes: int) -> None:
        self._max_processes = max_processes
        self._executor = ProcessPoolExecutor(
            max_workers=max_processes,
            mp_context=mp.get_context('spawn'),
            initializer=partial(_initializer, db_config))
        self._queue_name = 'judge_queue'
        self._conn: AsyncioConnection = None
        self._ch: Channel = None

    def __enter__(self) -> 'Worker':
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self._executor.shutdown(wait=False)
        if self._ch:
            self._ch.close()
        if self._conn:
            self._conn.close()

    def start(self) -> None:
        self._conn = AsyncioConnection(
            parameters=get_mq_conn_params(),
            on_open_callback=self._conn_on_open,
            on_open_error_callback=self._conn_on_open_error,
            on_close_callback=self._conn_on_close)
        asyncio.get_event_loop().run_forever()

    def _conn_on_open(self, _: AsyncioConnection) -> None:
        self._conn.channel(on_open_callback=self._ch_on_open)

    def _conn_on_open_error(self, _: AsyncioConnection,
                            err: AMQPError) -> None:
        pass  # TODO

    def _conn_on_close(self, _: AsyncioConnection, reason: AMQPError) -> None:
        pass  # TODO

    def _ch_on_open(self, ch: Channel) -> None:
        self._ch = ch
        ch.add_on_close_callback(self._ch_on_close)
        ch.queue_declare(
            queue=self._queue_name, callback=self._on_queue_declared)

    def _ch_on_close(self, ch: Channel, reason: AMQPError) -> None:
        # TODO
        try:
            self._conn.close()
        except Exception:
            pass

    def _on_queue_declared(self, method: pika.frame.Method) -> None:
        self._ch.basic_qos(
            prefetch_count=self._max_processes, callback=self._on_basic_qos_ok)

    def _on_basic_qos_ok(self, method: pika.frame.Method) -> None:
        self._start_consuming()

    def _start_consuming(self) -> None:
        self._ch.basic_consume(
            self._queue_name, on_message_callback=self._recv_message)

    def _recv_message(
            self,
            ch: Channel,
            method: pika.spec.Basic.Return,
            properties: pika.spec.BasicProperties,
            body: bytes) -> None:
        def _done(fut: Any) -> None:
            ch.basic_ack(delivery_tag=method.delivery_tag)

        try:
            contest_id, problem_id, submission_id = pickle.loads(body)
        except Exception:
            # invalid message. ignore.
            _done(None)
            return

        with transaction() as s:
            submission = s.query(Submission).with_for_update().filter(
                Submission.contest_id == contest_id,
                Submission.problem_id == problem_id,
                Submission.id == submission_id).first()
            if not submission or submission.status != JudgeStatus.Waiting:
                _done(None)
                return
            env = s.query(Environment).filter(
                Environment.id == submission.environment_id).first()
            problem = s.query(Problem).filter(
                Problem.contest_id == contest_id,
                Problem.id == problem_id).first()
            if not env or not problem:
                print('invalid submission (fk error). ignore')
                _done(None)  # TODO(kazuki): 外部キー制約を付与してこのチェックを削除する
                return
            task = submission.to_dict()
            task['environment'] = env.to_dict()
            task['problem'] = problem.to_dict()
            task['tests'] = []
            submission.status = JudgeStatus.Running
            testcases = s.query(TestCase).filter(
                TestCase.contest_id == contest_id,
                TestCase.problem_id == problem_id).all()
            for test in testcases:
                s.add(JudgeResult(
                    contest_id=contest_id,
                    problem_id=problem_id,
                    submission_id=submission_id,
                    test_id=test.id))
                task['tests'].append(test.to_dict())

        def _submit() -> None:
            print('submit to child process')
            future = self._executor.submit(run, task)
            future.add_done_callback(_done)
        asyncio.get_event_loop().call_soon_threadsafe(_submit)


def _initializer(db_config: dict) -> None:
    from penguin_judge.models import configure
    print('[worker:child] init {}'.format(db_config))
    configure(**db_config)


def main(db_config: dict, max_processes: int) -> None:
    with Worker(db_config, max_processes) as worker:
        worker.start()
