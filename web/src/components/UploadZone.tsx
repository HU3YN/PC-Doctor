import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { ErrorNotice } from "./Bits";

/** Drop a collector zip (or a PresentMon CSV) to upload and open its diagnosis. */
export function UploadZone() {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const navigate = useNavigate();
  const client = useQueryClient();

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      // Several files can be dropped at once; they are uploaded one by one.
      const results = [];
      for (const file of files) results.push(await api.uploadRun(file));
      return results;
    },
    onSuccess: (results) => {
      void client.invalidateQueries({ queryKey: ["runs"] });
      void client.invalidateQueries({ queryKey: ["stats"] });
      const only = results.length === 1 ? results[0] : undefined;
      // A guest gets a private link to their one run; the master opens it by id.
      if (only) navigate(only.share_key ? `/r/${only.share_key}` : `/runs/${only.run.id}`);
    },
  });

  function send(list: FileList | null) {
    const files = Array.from(list ?? []);
    if (files.length > 0) upload.mutate(files);
  }

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div
        className={over ? "dropzone over" : "dropzone"}
        role="button"
        tabIndex={0}
        aria-label="Upload a run"
        onClick={() => input.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          send(event.dataTransfer.files);
        }}
      >
        <strong>{upload.isPending ? "Analysing ..." : "Drop a run here, or click to choose a file"}</strong>
        <span className="muted small">
          The <code>PCDoctor-run-....zip</code> the collector made, or a PresentMon <code>.csv</code>
        </span>
        <input
          ref={input}
          type="file"
          accept=".zip,.csv"
          multiple
          hidden
          onChange={(event) => {
            send(event.target.files);
            event.target.value = "";
          }}
        />
      </div>
      <ErrorNotice error={upload.error} />
      {upload.isSuccess && upload.data.length > 1 && (
        <div className="notice good">{upload.data.length} runs uploaded.</div>
      )}
    </div>
  );
}
