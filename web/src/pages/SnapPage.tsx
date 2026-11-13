// What a phone sees after scanning the master's QR code: one big button.
// No sign-in. It can send photos and nothing else.
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api";
import { ErrorNotice, Loading } from "../components/Bits";

export function SnapPage() {
  const { token = "" } = useParams();
  const input = useRef<HTMLInputElement>(null);
  const [sent, setSent] = useState(0);
  const link = useQuery({ queryKey: ["photo-link", token], queryFn: () => api.photoLink(token), retry: false });
  const send = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) await api.sendPhoto(token, file);
      return files.length;
    },
    onSuccess: (count) => setSent((total) => total + count),
  });

  if (link.isLoading) return <Loading />;
  if (link.error) {
    return (
      <div className="snap stack">
        <h1>This link has expired</h1>
        <p>Ask for a new QR code on the master computer.</p>
      </div>
    );
  }
  return (
    <div className="snap stack">
      <h1>Send a photo to PC Doctor</h1>
      {link.data?.label && <p className="muted">For: {link.data.label}</p>}
      <button className="btn primary" disabled={send.isPending} onClick={() => input.current?.click()}>
        {send.isPending ? "Sending ..." : sent > 0 ? "Take another photo" : "Take a photo"}
      </button>
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        hidden
        aria-label="Photo"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length > 0) send.mutate(files);
          event.target.value = "";
        }}
      />
      {sent > 0 && !send.isPending && (
        <div className="notice good">
          {sent} {sent === 1 ? "photo" : "photos"} sent. It is on the master computer now.
        </div>
      )}
      <ErrorNotice error={send.error} />
      <p className="muted small">
        Error screen: fill the frame, square on, no glare. Motherboard: get the lit LEDs or the code
        display in focus. Photograph the PC, not people or paperwork.
      </p>
    </div>
  );
}
