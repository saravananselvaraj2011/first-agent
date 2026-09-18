import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App.jsx";

const TODAY = new Date().toISOString().slice(0, 10);

const OFFERS = [
  {
    id: "1", rank: 1, airline: "Air India", price: 579.48, currency: "USD", total_stops: 0,
    outbound: { from: "CHE", to: "TOK", date: "2027-03-10", depart: "05:25", arrive: "14:06", duration: "8h 41m", stops: 0, airline: "Air India", flight_number: "AI6554" },
    inbound: { from: "TOK", to: "CHE", date: "2027-03-17", depart: "06:25", arrive: "15:06", duration: "8h 41m", stops: 1, airline: "Air India", flight_number: "AI3033" },
  },
  {
    id: "2", rank: 2, airline: "Emirates", price: 707.71, currency: "USD", total_stops: 2,
    outbound: { from: "CHE", to: "TOK", date: "2027-03-10", depart: "09:00", arrive: "20:00", duration: "11h 00m", stops: 2, airline: "Emirates", flight_number: "EK100" },
    inbound: null,
  },
];

const WEATHER_DAY = {
  city: "Tokyo", date: "2027-03-10", severity: "moderate", source: "forecast", note: null,
  condition: "Moderate rain", temp_min_c: 12.4, temp_max_c: 18.6, wind_gust_kmh: 40.2, precipitation_mm: 14,
  warnings: [{ type: "rain", severity: "moderate", message: "Heavy rain expected (14 mm)." }],
};

const RESULT = {
  summary: "Book Air India; expect heavy rain on arrival.",
  flights: { offers: OFFERS, disclaimer: "Estimated fares (no flight API key configured) - illustrative, not bookable." },
  flights_error: null,
  weather: [WEATHER_DAY],
  weather_error: null,
  agents: [
    { name: "flights", text: "Flight agent says hi.", error: null },
    { name: "weather", text: "Weather agent says hi.", error: null },
  ],
  flight_source: "estimated",
};

/** Route fetch by URL; returns the spy so tests can inspect the calls. */
function mockFetch({ config = { flight_source: "estimated" }, trip = { ok: true, body: RESULT } } = {}) {
  const spy = vi.fn(async (url) => {
    if (url === "/api/config") return { ok: true, json: async () => config };
    if (url === "/api/trip") return { ok: trip.ok, json: async () => trip.body };
    throw new Error(`unexpected fetch ${url}`);
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

const tripCall = (spy) => spy.mock.calls.find(([url]) => url === "/api/trip");
const tripBody = (spy) => JSON.parse(tripCall(spy)[1].body);

async function fillAndSubmit(user, { from = "Chennai", to = "Tokyo", start, back } = {}) {
  await user.type(screen.getByLabelText("From"), from);
  await user.type(screen.getByLabelText("To"), to);
  if (start) {
    await user.clear(screen.getByLabelText("Start date"));
    await user.type(screen.getByLabelText("Start date"), start);
  }
  if (back) await user.type(screen.getByLabelText(/Return date/), back);
  await user.click(screen.getByRole("button", { name: /plan this trip/i }));
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("form", () => {
  it("shows the four inputs with the requested labels", () => {
    mockFetch();
    render(<App />);
    expect(screen.getByLabelText("From")).toBeInTheDocument();
    expect(screen.getByLabelText("To")).toBeInTheDocument();
    expect(screen.getByLabelText("Start date")).toBeInTheDocument();
    expect(screen.getByLabelText(/Return date/)).toBeInTheDocument();
  });

  it("no longer uses the old 'Travel date' label", () => {
    mockFetch();
    render(<App />);
    expect(screen.queryByText(/travel date/i)).not.toBeInTheDocument();
  });

  it("puts the (optional) tag on the same line as 'Return date'", () => {
    mockFetch();
    render(<App />);
    const label = screen.getByLabelText(/Return date/).closest("label");
    const inline = within(label).getByText(/Return date/);
    // Both texts live inside ONE span, so they can't stack as separate flex rows.
    expect(inline).toHaveTextContent("Return date (optional)");
    expect(within(inline).getByText("(optional)")).toBeInTheDocument();
  });

  it("does not mark the start date as optional", () => {
    mockFetch();
    render(<App />);
    expect(screen.getByLabelText("Start date").closest("label")).not.toHaveTextContent("optional");
  });

  it("defaults the start date to today and leaves return empty", () => {
    mockFetch();
    render(<App />);
    expect(screen.getByLabelText("Start date")).toHaveValue(TODAY);
    expect(screen.getByLabelText(/Return date/)).toHaveValue("");
  });

  it("does not allow picking a start date in the past", () => {
    mockFetch();
    render(<App />);
    expect(screen.getByLabelText("Start date")).toHaveAttribute("min", TODAY);
  });

  it("does not allow a return date before the start date", async () => {
    mockFetch();
    const user = userEvent.setup();
    render(<App />);
    await user.clear(screen.getByLabelText("Start date"));
    await user.type(screen.getByLabelText("Start date"), "2027-03-10");
    expect(screen.getByLabelText(/Return date/)).toHaveAttribute("min", "2027-03-10");
  });

  it("has a submit button", () => {
    mockFetch();
    render(<App />);
    expect(screen.getByRole("button", { name: /plan this trip/i })).toBeEnabled();
  });
});

describe("client-side validation", () => {
  it("asks for both cities when they are empty, without calling the API", async () => {
    const spy = mockFetch();
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /plan this trip/i }));
    expect(screen.getByText(/enter a start city, a destination city and a start date/i)).toBeInTheDocument();
    expect(tripCall(spy)).toBeUndefined();
  });

  it("rejects a whitespace-only city", async () => {
    const spy = mockFetch();
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByLabelText("From"), "   ");
    await user.type(screen.getByLabelText("To"), "Tokyo");
    await user.click(screen.getByRole("button", { name: /plan this trip/i }));
    expect(screen.getByText(/enter a start city/i)).toBeInTheDocument();
    expect(tripCall(spy)).toBeUndefined();
  });

  it("rejects a cleared start date", async () => {
    const spy = mockFetch();
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByLabelText("From"), "Chennai");
    await user.type(screen.getByLabelText("To"), "Tokyo");
    await user.clear(screen.getByLabelText("Start date"));
    await user.click(screen.getByRole("button", { name: /plan this trip/i }));
    expect(screen.getByText(/enter a start city/i)).toBeInTheDocument();
    expect(tripCall(spy)).toBeUndefined();
  });
});

describe("request", () => {
  it("posts the trip as JSON with a null return date for a one-way trip", async () => {
    const spy = mockFetch();
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user, { start: "2027-03-10" });
    await screen.findByText(RESULT.summary);
    expect(tripCall(spy)[1].method).toBe("POST");
    expect(tripBody(spy)).toEqual({
      origin: "Chennai", destination: "Tokyo", depart_date: "2027-03-10", return_date: null,
    });
  });

  it("includes the return date when one is entered", async () => {
    const spy = mockFetch();
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user, { start: "2027-03-10", back: "2027-03-17" });
    await screen.findByText(RESULT.summary);
    expect(tripBody(spy).return_date).toBe("2027-03-17");
  });

  it("trims whitespace around city names", async () => {
    const spy = mockFetch();
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user, { from: "  Chennai ", to: " Tokyo  " });
    await screen.findByText(RESULT.summary);
    expect(tripBody(spy)).toMatchObject({ origin: "Chennai", destination: "Tokyo" });
  });

  it("disables the button and shows progress while the agents work", async () => {
    let release;
    vi.stubGlobal("fetch", vi.fn((url) => {
      if (url === "/api/config") return Promise.resolve({ ok: true, json: async () => ({}) });
      return new Promise((resolve) => { release = () => resolve({ ok: true, json: async () => RESULT }); });
    }));
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user);
    const busy = await screen.findByRole("button", { name: /agents are working/i });
    expect(busy).toBeDisabled();
    release();
    await screen.findByText(RESULT.summary);
    expect(screen.getByRole("button", { name: /plan this trip/i })).toBeEnabled();
  });
});

describe("results", () => {
  async function renderResult(result = RESULT) {
    mockFetch({ trip: { ok: true, body: result } });
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user, { start: "2027-03-10", back: "2027-03-17" });
    await screen.findByText(result.summary);
    return user;
  }

  it("shows the briefing", async () => {
    await renderResult();
    expect(screen.getByRole("heading", { name: "Briefing" })).toBeInTheDocument();
    expect(screen.getByText(RESULT.summary)).toBeInTheDocument();
  });

  it("lists flights in the order given, cheapest first, with prices", async () => {
    await renderResult();
    const airlines = screen.getAllByText(/^(Air India|Emirates)$/).map((el) => el.textContent);
    expect(airlines).toEqual(["Air India", "Emirates"]);
    expect(screen.getByText("$579")).toBeInTheDocument();
    expect(screen.getByText("$708")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /flights/i })).toHaveTextContent("cheapest first");
  });

  it("badges only the cheapest offer", async () => {
    await renderResult();
    const badges = screen.getAllByText("Cheapest");
    expect(badges).toHaveLength(1);
    expect(badges[0].closest(".offer")).toHaveTextContent("Air India");
    expect(badges[0].closest(".offer")).toHaveClass("cheapest");
  });

  it("shows outbound and return legs with stops and flight numbers", async () => {
    await renderResult();
    // Both offers fly CHE → TOK outbound; only the first has a TOK → CHE return.
    expect(screen.getAllByText("CHE → TOK", { selector: ".leg-route" })).toHaveLength(2);
    expect(screen.getAllByText("TOK → CHE", { selector: ".leg-route" })).toHaveLength(1);
    expect(screen.getByText(/8h 41m · Non-stop · AI6554/)).toBeInTheDocument();
    expect(screen.getByText(/8h 41m · 1 stop · AI3033/)).toBeInTheDocument();
    expect(screen.getByText(/11h 00m · 2 stops · EK100/)).toBeInTheDocument();
  });

  it("omits the return leg for a one-way offer", async () => {
    await renderResult();
    const emirates = screen.getByText("Emirates").closest(".offer");
    expect(within(emirates).getByText("Out")).toBeInTheDocument();
    expect(within(emirates).queryByText("Back")).not.toBeInTheDocument();
  });

  it("shows the estimated-fares disclaimer", async () => {
    await renderResult();
    expect(screen.getByText(/illustrative, not bookable/i)).toBeInTheDocument();
  });

  it("renders the weather warning card for the destination", async () => {
    await renderResult();
    expect(screen.getByRole("heading", { name: /weather at tokyo/i })).toBeInTheDocument();
    expect(screen.getByText("Tokyo · 2027-03-10")).toBeInTheDocument();
    expect(screen.getByText("Weather warning")).toBeInTheDocument();
    expect(screen.getByText("Heavy rain expected (14 mm).")).toBeInTheDocument();
    expect(screen.getByText(/12–19°C/)).toBeInTheDocument();
  });

  it("colour-codes the weather card by severity", async () => {
    await renderResult();
    expect(screen.getByText("Tokyo · 2027-03-10").closest(".weather-card")).toHaveClass("severity-moderate");
  });

  it("shows 'No warnings' for a calm day", async () => {
    await renderResult({ ...RESULT, weather: [{ ...WEATHER_DAY, severity: "none", warnings: [] }] });
    expect(screen.getByText("No warnings")).toBeInTheDocument();
  });

  it("labels high severity as severe", async () => {
    await renderResult({ ...RESULT, weather: [{ ...WEATHER_DAY, severity: "high" }] });
    expect(screen.getByText("Severe weather warning")).toBeInTheDocument();
  });

  it("explains when weather is seasonal averages rather than a forecast", async () => {
    await renderResult({ ...RESULT, weather: [{ ...WEATHER_DAY, source: "seasonal_normals", note: "not a forecast." }] });
    expect(screen.getByText(/not a forecast/)).toBeInTheDocument();
  });

  it("renders one weather card per date on a round trip", async () => {
    await renderResult({ ...RESULT, weather: [WEATHER_DAY, { ...WEATHER_DAY, date: "2027-03-17" }] });
    expect(screen.getByText("Tokyo · 2027-03-10")).toBeInTheDocument();
    expect(screen.getByText("Tokyo · 2027-03-17")).toBeInTheDocument();
  });

  it("lets you expand each agent's own report", async () => {
    const user = await renderResult();
    await user.click(screen.getByText("What each agent reported"));
    expect(screen.getByText("Flight agent says hi.")).toBeInTheDocument();
    expect(screen.getByText("Weather agent says hi.")).toBeInTheDocument();
  });
});

describe("partial failures", () => {
  it("still shows flights when the weather lookup failed", async () => {
    mockFetch({ trip: { ok: true, body: { ...RESULT, weather: [], weather_error: "WeatherLookupError: down" } } });
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user);
    expect(await screen.findByText(/weather lookup failed: WeatherLookupError: down/i)).toBeInTheDocument();
    expect(screen.getByText("Air India")).toBeInTheDocument();
  });

  it("still shows weather when the flight search failed", async () => {
    mockFetch({ trip: { ok: true, body: { ...RESULT, flights: null, flights_error: "No flights found" } } });
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user);
    expect(await screen.findByText(/flight search failed: No flights found/i)).toBeInTheDocument();
    expect(screen.getByText("Heavy rain expected (14 mm).")).toBeInTheDocument();
  });
});

describe("errors", () => {
  it("shows the server's error detail for an HTTP failure", async () => {
    mockFetch({ trip: { ok: false, body: { detail: "The travel date is in the past." } } });
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user);
    expect(await screen.findByText("The travel date is in the past.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Briefing" })).not.toBeInTheDocument();
  });

  it("falls back to a generic message when the error has no detail", async () => {
    mockFetch({ trip: { ok: false, body: {} } });
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user);
    expect(await screen.findByText("Something went wrong.")).toBeInTheDocument();
  });

  it("shows a network failure and re-enables the button", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => {
      if (url === "/api/config") return { ok: true, json: async () => ({}) };
      throw new Error("Failed to fetch");
    }));
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user);
    expect(await screen.findByText("Failed to fetch")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /plan this trip/i })).toBeEnabled();
  });

  it("clears the previous result when a new search errors", async () => {
    const spy = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ flight_source: "estimated" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => RESULT })
      .mockResolvedValueOnce({ ok: false, json: async () => ({ detail: "Nope." }) });
    vi.stubGlobal("fetch", spy);
    const user = userEvent.setup();
    render(<App />);
    await fillAndSubmit(user);
    await screen.findByText(RESULT.summary);
    await user.click(screen.getByRole("button", { name: /plan this trip/i }));
    await screen.findByText("Nope.");
    expect(screen.queryByText(RESULT.summary)).not.toBeInTheDocument();
  });
});

describe("estimated-fares notice", () => {
  it("is shown when the server says fares are estimated", async () => {
    mockFetch({ config: { flight_source: "estimated" } });
    render(<App />);
    expect(await screen.findByText(/no flight api key configured/i)).toBeInTheDocument();
  });

  it("is hidden when real Amadeus fares are configured", async () => {
    mockFetch({ config: { flight_source: "amadeus" } });
    render(<App />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/config"));
    expect(screen.queryByText(/no flight api key configured/i)).not.toBeInTheDocument();
  });

  it("does not break the page if /api/config is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<App />);
    expect(screen.getByRole("heading", { name: /trip agent/i })).toBeInTheDocument();
  });
});
