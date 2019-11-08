import { customElement, LitElement, html, css } from 'lit-element';

@customElement('x-icon')
export class IconElement extends LitElement {
  render() {
    return html`<slot></slot>`
  }

  static get styles() {
    return css`
    :host {
        font-family: 'Material Icons';
        font-weight: normal;
        font-style: normal;
        display: inline-block;
        line-height: 1;
        text-transform: none;
        letter-spacing: normal;
        word-wrap: normal;
        white-space: nowrap;
        direction: ltr;
        /* Support for all WebKit browsers. */
        -webkit-font-smoothing: antialiased;
        /* Support for Safari and Chrome. */
        text-rendering: optimizeLegibility;
        /* Support for Firefox. */
        -moz-osx-font-smoothing: grayscale;
        /* Support for IE. */
        font-feature-settings: 'liga';
        overflow: hidden;
      }
    `
  }
}
