/** Frame the approved artwork without its presentation margins. */
export default function Logo({ navigation = false }: { navigation?: boolean }) {
  if (navigation) {
    return <>
      <svg className="nav-logo-icon" viewBox="306 212 290 360" aria-hidden="true" focusable="false">
        <image href="/images/forma-logo-document-smile-v2.png" width="1942" height="809" />
      </svg>
      <span className="nav-logo-wordmark">Forma</span>
    </>;
  }
  return (
    <svg className="forma-logo" viewBox="306 212 1330 360" aria-hidden="true" focusable="false">
      <image href="/images/forma-logo-document-smile-v2.png" width="1942" height="809" />
    </svg>
  );
}
