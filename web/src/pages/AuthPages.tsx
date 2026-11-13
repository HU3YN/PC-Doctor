// Signing in, and creating the master account the first time.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { ErrorNotice } from "../components/Bits";

export function LoginPage() {
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
      <h1>Master sign-in</h1>
      <p className="muted small">For the technician. Runs, the work log and photos are only visible here.</p>
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
