// Getting the collector onto a PC: download it from this computer.
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { ErrorNotice } from "../components/Bits";

export function GetCollectorPage() {
  const info = useQuery({ queryKey: ["collector"], queryFn: api.collector });
  const local = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  const addresses = info.data?.lan_addresses ?? [];
  const port = window.location.port ? `:${window.location.port}` : "";

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Get the collector</h1>
          <p className="sub">
            The collector is a small read-only script. It runs from a USB stick and saves what it
            finds back onto the stick. The one thing it can install is a temporary temperature
            driver, and only if you say yes.
          </p>
        </div>
        {info.data?.available && (
          <a className="btn primary" href="/api/collector.zip" download>
            Download the collector (.zip)
          </a>
        )}
      </div>
      <ErrorNotice error={info.error} />
      {info.data && !info.data.available && (
        <div className="notice warn">The collector files are not on this server.</div>
      )}

      <div className="card">
        <h2>With a USB stick</h2>
        <ol className="steps" style={{ margin: 0 }}>
          <li>
            Download the zip above and unpack it onto a USB stick. You only do this once - keep the
            stick in your bag.
          </li>
          <li>
            Plug the stick into the PC you are checking and double-click <code>PCDoctor.cmd</code>.
          </li>
          <li>
            Choose a quick check (about 20 seconds) or a 5-minute capture. The results are saved in
            the <code>runs</code> folder <b>on the stick</b>.
          </li>
          <li>
            Bring the stick back to this computer, open <b>Runs</b>, and drop the{" "}
            <code>.zip</code> files from the stick&apos;s <code>runs</code> folder onto the page -
            several at once is fine.
          </li>
        </ol>
        {info.data && (
          <div className="muted small stack" style={{ marginTop: 10, gap: 6 }}>
            {info.data.includes_presentmon ? (
              <p>
                Frame-time captures work straight from this one download: PresentMon (Intel&apos;s
                frame-time recorder) is inside the zip, unmodified, with Intel&apos;s licence. The
                collector checks Intel&apos;s signature before running it.
              </p>
            ) : (
              <p>
                PresentMon (Intel&apos;s frame-time recorder, needed for frame times) is not in this
                server&apos;s zip. The collector fetches and checks it itself on the first capture, if
                the PC it runs on is online.
              </p>
            )}
            {info.data.includes_temperature_tools ? (
              <p>
                CPU temperature works from the same download: the collector asks before installing a
                temporary driver for the capture, and removes it afterwards.
              </p>
            ) : (
              <p>
                CPU temperature needs LibreHardwareMonitor started by hand: this server&apos;s zip
                does not include the temperature driver.
              </p>
            )}
            {info.data.sha256 && (
              <p>
                SHA-256 of the collector zip:{" "}
                <code style={{ wordBreak: "break-all" }}>{info.data.sha256}</code>.{" "}
                {info.data.includes_presentmon ? (
                  <>
                    It is the same file as the collector release on GitHub for this version; check a
                    copy with{" "}
                    <code>gh attestation verify PCDoctor-collector.zip --repo HU3YN/PC-Doctor</code> or
                    by comparing this hash with the release page.
                  </>
                ) : (
                  <>
                    Without PresentMon inside, it is not the same file as the GitHub release, so it
                    will not match the release&apos;s hash or attestation.
                  </>
                )}
              </p>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Straight from the PC being checked</h2>
        <p>
          If that PC is on the same network as this one, open this page in its browser and download
          the collector there - no stick needed to get it. It can also send its result straight back.
        </p>
        {local ? (
          <div className="stack" style={{ gap: 6, marginTop: 8 }}>
            <p>
              You are looking at this page on the master computer itself. Other PCs need its network
              address instead of <code>localhost</code>
              {addresses.length > 0 ? ":" : "."}
            </p>
            {addresses.map((address) => (
              <p key={address}>
                <code>
                  http://{address}
                  {port}/get
                </code>
              </p>
            ))}
            <p className="muted small">
              This only works if PC Doctor was started for the network (<code>Start-PCDoctor.cmd -Lan</code>
              ). There are no logins yet, so do that only on a network you trust.
            </p>
          </div>
        ) : (
          <p style={{ marginTop: 8 }}>
            To send the result back without a stick, run the collector like this:
            <br />
            <code>PCDoctor.cmd -UploadUrl {window.location.origin}</code>
          </p>
        )}
      </div>

      <div className="card">
        <h2>The PC will not start at all?</h2>
        <p>
          Nothing can run on it, so use <a href="/wont-start">Won&apos;t start</a>: upload a photo of
          the error screen, or pick what you see and get a checklist.
        </p>
      </div>
    </div>
  );
}
