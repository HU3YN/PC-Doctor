// The master's account page: other ways to sign in, and who else has an account.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { ErrorNotice } from "../components/Bits";
import { formatDateTime } from "../format";
import { ProviderButtons } from "./AuthPages";

/** Change the password, and sign out on every browser. */
function Security() {
  const client = useQueryClient();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({
    mutationFn: () => api.changePassword({ current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent("");
      setNext("");
    },
  });
  const navigate = useNavigate();
  const everywhere = useMutation({
    mutationFn: api.logoutEverywhere,
    onSuccess: async () => {
      client.clear(); // forget everything the master had on screen, as Sign out does
      navigate("/");
      await client.invalidateQueries();
    },
  });
  return (
    <section className="card stack" style={{ gap: 10 }}>
      <h2>Password and sessions</h2>
      <form
        className="stack"
        style={{ gap: 10, maxWidth: 420 }}
        onSubmit={(event) => {
          event.preventDefault();
          change.mutate();
        }}
      >
        <label className="field">
          Current password
          <input type="password" required autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label className="field">
          New password (10 characters or more)
          <input type="password" required minLength={10} autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        </label>
        <ErrorNotice error={change.error} />
        {change.isSuccess && <p className="small">Password changed. Every other browser has been signed out.</p>}
        <button className="btn primary" disabled={change.isPending}>
          Change password
        </button>
      </form>
      <p className="muted small">
        Lost a phone or used a shared computer? Sign out everywhere ends every session of this account, this one
        included.
      </p>
      <div>
        <button
          className="btn"
          disabled={everywhere.isPending}
          onClick={() => {
            if (window.confirm("Sign out on every browser, this one included?")) everywhere.mutate();
          }}
        >
          Sign out everywhere
        </button>
      </div>
      <ErrorNotice error={everywhere.error} />
    </section>
  );
}

export function AccountPage() {
  const client = useQueryClient();
  const oauth = useQuery({ queryKey: ["oauth"], queryFn: api.oauth, staleTime: Infinity });
  const identities = useQuery({ queryKey: ["identities"], queryFn: api.identities });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: api.accounts });
  const unlink = useMutation({
    mutationFn: (id: number) => api.unlinkIdentity(id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["identities"] }),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.removeAccount(id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["accounts"] }),
  });
  const configured = (oauth.data?.providers.length ?? 0) > 0;
  const members = (accounts.data ?? []).filter((account) => account.role !== "master");

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Account</h1>
          <p className="sub">Sign-in with Discord or Google, and the people who have their own account.</p>
        </div>
      </div>
      <ErrorNotice error={identities.error ?? accounts.error ?? unlink.error ?? remove.error} />

      <Security />

      <section className="card stack" style={{ gap: 10 }}>
        <h2>Your sign-in</h2>
        {!configured && (
          <p className="muted small">
            Sign-in with Discord or Google is not set up on this server. It needs <code>PCDOCTOR_PUBLIC_URL</code> and
            a client id and secret in <code>.env</code> - see <code>docs/oauth.md</code>. Your password keeps working.
          </p>
        )}
        {(identities.data ?? []).map((identity) => (
          <div key={identity.id} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              {identity.provider} <span className="muted small">linked {formatDateTime(identity.linked_at)}</span>
            </span>
            <button className="btn quiet" disabled={unlink.isPending} onClick={() => unlink.mutate(identity.id)}>
              Unlink
            </button>
          </div>
        ))}
        <ProviderButtons intent="link" />
        {configured && (
          <p className="muted small">
            Linking lets you sign in as the master with that account. Only its id is stored - no name, no email.
          </p>
        )}
      </section>

      <section className="card stack" style={{ gap: 10 }}>
        <h2>Members</h2>
        <p className="muted small">
          {oauth.data?.signup
            ? "Sign-up is open: anyone who signs in with Discord or Google gets a member account."
            : "Sign-up is closed (PCDOCTOR_OAUTH_SIGNUP is off): nobody new can make an account."}{" "}
          A member sees only the runs they uploaded - never the work log, photos or other runs.
        </p>
        {members.length === 0 && <p className="muted">No members.</p>}
        {members.map((account) => (
          <div key={account.id} className="row" style={{ justifyContent: "space-between" }}>
            <span>
              {account.username}{" "}
              <span className="muted small">
                {account.providers.join(", ")} · since {formatDateTime(account.created_at)}
              </span>
            </span>
            <button
              className="btn quiet"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm("Remove this member? Their runs stay in your list.")) remove.mutate(account.id);
              }}
            >
              Remove
            </button>
          </div>
        ))}
      </section>
    </div>
  );
}
