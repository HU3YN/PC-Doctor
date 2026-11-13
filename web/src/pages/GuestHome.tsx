// What someone without an account sees: check one PC, get its diagnosis.
import { Link } from "react-router-dom";

import { UploadZone } from "../components/UploadZone";

export function GuestHome() {
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Check a PC</h1>
          <p className="sub">
            Find out what is wrong with a Windows PC, in plain English. No account needed.
          </p>
        </div>
      </div>
      <div className="card">
        <ol className="steps" style={{ margin: 0 }}>
          <li>
            <a href="/api/collector.zip" download>
              Download the collector
            </a>{" "}
            and unpack it. It is a small read-only script: it installs nothing and changes nothing.
          </li>
          <li>
            Double-click <code>PCDoctor.cmd</code> and choose a quick check or a 5-minute capture.
          </li>
          <li>
            Drop the <code>.zip</code> it makes below. You get a private link to your diagnosis.
          </li>
        </ol>
      </div>
      <UploadZone />
      <p className="muted small">
        Only you can open your result, through its link. The collector never reads names, files or
        serial numbers. PC will not start at all? See the <Link to="/wont-start">no-boot checklist</Link>.
      </p>
    </div>
  );
}
