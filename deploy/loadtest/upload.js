// k6 load test for the upload service (Phase 3).
//
//   python deploy/loadtest/make_run.py          writes deploy/loadtest/run.zip (a made-up run)
//   k6 run deploy/loadtest/upload.js
//   k6 run -e BASE=http://localhost:8090 -e VUS=20 -e DURATION=2m deploy/loadtest/upload.js
//
// Test your own machine or your own server only. The service allows 30 uploads
// an hour per address, so start it with PCDOCTOR_UPLOADS_PER_HOUR=1000000 for
// the test - never in normal use.
//
// What to record in docs/results.md: requests per second, the 95th percentile
// time, the error rate, and the load (VUs, duration, machine).
import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE = __ENV.BASE || "http://localhost:8090";
const run = open("./run.zip", "b");
const diagnosed = new Trend("upload_to_diagnosis_ms", true);
const failed = new Rate("failed_uploads");

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || "1m",
  thresholds: {
    failed_uploads: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
  },
};

export default function () {
  // A different label each time; the file is the same, which the worker
  // recognises (same content = same run), so the database does not fill up.
  const started = Date.now();
  const response = http.post(`${BASE}/upload`, {
    file: http.file(run, "run.zip", "application/zip"),
    label: `load test ${__VU}-${__ITER}`,
  });
  const accepted = check(response, { "accepted (202)": (r) => r.status === 202 });
  failed.add(!accepted);
  if (!accepted) return;

  const statusUrl = `${BASE}${response.json("status_url")}`;
  for (let attempt = 0; attempt < 50; attempt++) {
    const state = http.get(statusUrl, { tags: { name: "job status" } }).json("status");
    if (state === "done") {
      diagnosed.add(Date.now() - started);
      return;
    }
    if (state === "failed") {
      failed.add(true);
      return;
    }
    sleep(0.2);
  }
  failed.add(true); // never finished
}
