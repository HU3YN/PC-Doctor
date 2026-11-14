// Signing in, and creating the master account the first time.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { ErrorNotice } from "../components/Bits";

// Why a Discord or Google sign-in did not go through (set by the server).
const PROBLEMS: Record<string, string> = {
  expired: "That sign-in took too long or was not started here. Try again.",
  provider: "The sign-in service did not confirm who you are. Try again.",
  not_linked: "That account is not known here. The master has to link it first, or open sign-up.",
  taken: "That account is already linked to someone else here.",
};

/** Buttons for the sign-in services this server has been set up with (often none). */
export function ProviderButtons({ intent }: { intent: "login" | "link" }) {
  const oauth = useQuery({ queryKey: ["oauth"], queryFn: api.oauth, staleTime: Infinity });
  const providers = oauth.data?.providers ?? [];
  if (providers.length === 0) return null;
  return (
    <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
      {providers.map((provider) => (
        // A plain link: the browser has to leave for the provider and come back.
        <a key={provider.name} className="btn" href={`/api/auth/oauth/${provider.name}/start?intent=${intent}`}>
          {intent === "link" ? "Link" : "Sign in with"} {provider.label}
        </a>
      ))}
    </div>
  );
}

/** Under the provider buttons: what they are for, so the password form below reads as the technician's. */
function ProviderNote() {
  const oauth = useQuery({ queryKey: ["oauth"], queryFn: api.oauth, staleTime: Infinity });
  if (!oauth.data || oauth.data.providers.length === 0) return null;
  return (
    <p className="muted small">
      {oauth.data.signup
        ? "Use Discord or Google to see the runs you uploaded. Only the account's id is stored."
        : "Discord or Google work only for accounts the technician has linked."}
    </p>
  );
}

export function LoginPage() {
  const [params] = useSearchParams();
  const problem = PROBLEMS[params.get("problem") ?? ""];
  const client = useQueryClient();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => api.login({ username, password }),
    onSuccess: async () => {
      await client.invalidateQueries();
      navigate("/");
    },
  });
  return (
    <form
      className="card stack narrow"
      onSubmit={(event) => {
        event.preventDefault();
        login.mutate();
      }}
    >
      <h1>Sign in</h1>
      {problem && <div className="notice warn">{problem}</div>}
      <ProviderButtons intent="login" />
      <ProviderNote />
      <p className="muted small">
        The technician signs in here. Runs, the work log and photos are only visible after signing in.
      </p>
      <label className="field">
        Username
        <input required autoFocus autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
      </label>
      <label className="field">
        Password
        <input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
      </label>
      <ErrorNotice error={login.error} />
      <button className="btn primary" disabled={login.isPending}>
        {login.isPending ? "Signing in ..." : "Sign in"}
      </button>
    </form>
  );
}

export function SetupPage() {
  const client = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const setup = useMutation({
    mutationFn: () => api.setup({ username, password, setup_code: code }),
    onSuccess: () => client.invalidateQueries(),
  });
  return (
    <form
      className="card stack narrow"
      onSubmit={(event) => {
        event.preventDefault();
        setup.mutate();
      }}
    >
      <h1>Create the master account</h1>
      <p className="muted small">
        One time only. This account owns everything stored here: runs, the work log and photos.
      </p>
      <label className="field">
        Setup code
        <span className="hint">
          Shown in the window that started PC Doctor, and saved in <code>data/setup-code.txt</code>. It
          proves you are at the master computer.
        </span>
        <input required autoFocus value={code} onChange={(event) => setCode(event.target.value)} />
      </label>
      <label className="field">
        Username
        <input required autoComplete="username" maxLength={64} value={username} onChange={(event) => setUsername(event.target.value)} />
      </label>
      <label className="field">
        Password
        <span className="hint">At least 10 characters. A few random words work well.</span>
        <input required type="password" minLength={10} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
      </label>
      <ErrorNotice error={setup.error} />
      <button className="btn primary" disabled={setup.isPending}>
        {setup.isPending ? "Creating ..." : "Create account"}
      </button>
    </form>
  );
}
