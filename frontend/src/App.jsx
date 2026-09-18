import { useEffect, useState } from "react";

const SEVERITY_LABEL = {
  none: "No warnings",
  low: "Heads-up",
  moderate: "Weather warning",
  high: "Severe weather warning",
};

function today() {
  return new Date().toISOString().slice(0, 10);
}

function formatPrice(amount, currency) {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${amount} ${currency || ""}`.trim();
  }
}

function stopsLabel(stops) {
  if (stops === 0) return "Non-stop";
  return stops === 1 ? "1 stop" : `${stops} stops`;
}

function Leg({ leg, label }) {
  if (!leg) return null;
  return (
    <div className="leg">
      <span className="leg-label">{label}</span>
      <span className="leg-route">
        {leg.from} → {leg.to}
      </span>
      <span className="leg-times">
        {leg.depart} – {leg.arrive}
      </span>
      <span className="leg-meta">
        {leg.duration} · {stopsLabel(leg.stops)} · {leg.flight_number}
      </span>
    </div>
  );
}

function WeatherCard({ day }) {
  const severity = day.severity || "none";
  return (
    <div className={`weather-card severity-${severity}`}>
      <div className="weather-head">
        <strong>
          {day.city} · {day.date}
        </strong>
        <span className={`badge badge-${severity}`}>{SEVERITY_LABEL[severity]}</span>
      </div>
      <p className="weather-conditions">
        {day.condition}
        {day.temp_max_c != null && ` · ${Math.round(day.temp_min_c)}–${Math.round(day.temp_max_c)}°C`}
        {day.wind_gust_kmh != null && ` · gusts ${Math.round(day.wind_gust_kmh)} km/h`}
        {day.precipitation_mm != null && ` · ${day.precipitation_mm} mm rain`}
      </p>
      {day.warnings?.length > 0 && (
        <ul className="warnings">
          {day.warnings.map((warning, index) => (
            <li key={index} className={`warning-${warning.severity}`}>
              {warning.message}
            </li>
          ))}
        </ul>
      )}
      {day.note && <p className="note">{day.note}</p>}
    </div>
  );
}

export default function App() {
  const [form, setForm] = useState({
    origin: "",
    destination: "",
    departDate: today(),
    returnDate: "",
  });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [flightSource, setFlightSource] = useState(null);

  useEffect(() => {
    fetch("/api/config")
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => data && setFlightSource(data.flight_source))
      .catch(() => {});
  }, []);

  function update(field) {
    return (event) => setForm({ ...form, [field]: event.target.value });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const origin = form.origin.trim();
    const destination = form.destination.trim();

    if (!origin || !destination || !form.departDate) {
      setError("Enter a start city, a destination city and a start date.");
      setResult(null);
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch("/api/trip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin,
          destination,
          depart_date: form.departDate,
          return_date: form.returnDate || null,
        }),
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Something went wrong.");
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const offers = result?.flights?.offers ?? [];

  return (
    <main className="app">
      <h1>✈️ Trip Agent</h1>
      <p className="subtitle">
        Two Claude agents work in parallel — one searches flights, one checks the
        destination weather — and a third writes the briefing.
      </p>

      <form onSubmit={handleSubmit}>
        <div className="row">
          <label>
            From
            <input
              type="text"
              placeholder="e.g. London"
              value={form.origin}
              onChange={update("origin")}
            />
          </label>
          <label>
            To
            <input
              type="text"
              placeholder="e.g. Tokyo"
              value={form.destination}
              onChange={update("destination")}
            />
          </label>
        </div>
        <div className="row">
          <label>
            <span>Start date</span>
            <input
              type="date"
              min={today()}
              value={form.departDate}
              onChange={update("departDate")}
            />
          </label>
          <label>
            <span>
              Return date <span className="optional">(optional)</span>
            </span>
            <input
              type="date"
              min={form.departDate || today()}
              value={form.returnDate}
              onChange={update("returnDate")}
            />
          </label>
        </div>
        <button type="submit" disabled={loading}>
          {loading ? "Agents are working…" : "Plan this trip"}
        </button>
      </form>

      {flightSource === "estimated" && (
        <p className="note source-note">
          No flight API key configured — fares below are estimated from real city
          distances, not bookable offers.
        </p>
      )}

      {error && <p className="error">{error}</p>}

      {result && (
        <section className="results">
          <div className="briefing">
            <h2>Briefing</h2>
            <p>{result.summary}</p>
          </div>

          {result.weather?.length > 0 && (
            <div className="block">
              <h2>Weather at {result.weather[0].city}</h2>
              {result.weather.map((day) => (
                <WeatherCard key={day.date} day={day} />
              ))}
            </div>
          )}
          {result.weather_error && (
            <p className="error">Weather lookup failed: {result.weather_error}</p>
          )}

          <div className="block">
            <h2>
              Flights{offers.length > 0 && <span className="muted"> — cheapest first</span>}
            </h2>
            {result.flights?.disclaimer && (
              <p className="note">{result.flights.disclaimer}</p>
            )}
            {result.flights_error && (
              <p className="error">Flight search failed: {result.flights_error}</p>
            )}
            {offers.map((offer) => (
              <div key={offer.id} className={`offer${offer.rank === 1 ? " cheapest" : ""}`}>
                <div className="offer-head">
                  <span className="airline">{offer.airline}</span>
                  <span className="price">
                    {formatPrice(offer.price, offer.currency)}
                    {offer.rank === 1 && <span className="badge badge-cheap">Cheapest</span>}
                  </span>
                </div>
                <Leg leg={offer.outbound} label="Out" />
                <Leg leg={offer.inbound} label="Back" />
              </div>
            ))}
          </div>

          <details className="block agents">
            <summary>What each agent reported</summary>
            {result.agents?.map((agent) => (
              <div key={agent.name} className="agent-report">
                <strong>{agent.name} agent</strong>
                <p>{agent.text || agent.error}</p>
              </div>
            ))}
          </details>
        </section>
      )}
    </main>
  );
}
