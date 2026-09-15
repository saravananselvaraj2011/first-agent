import { useState } from "react";

export default function App() {
  const [city, setCity] = useState("");
  const [loading, setLoading] = useState(false);
  const [reply, setReply] = useState(null);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = city.trim();
    if (!trimmed) {
      setError("Please enter a city name.");
      setReply(null);
      return;
    }

    setLoading(true);
    setError(null);
    setReply(null);

    try {
      const response = await fetch("/api/weather", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ city: trimmed }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Something went wrong.");
      }

      setReply(data.reply);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app">
      <h1>⛅ Weather Agent</h1>
      <p className="subtitle">
        Enter a city and Claude will call a weather tool to look it up.
      </p>

      <form onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="e.g. Tokyo"
          value={city}
          onChange={(event) => setCity(event.target.value)}
        />
        <button type="submit" disabled={loading}>
          {loading ? "Asking the agent…" : "Get weather"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}
      {reply && <p className="success">{reply}</p>}
    </main>
  );
}
