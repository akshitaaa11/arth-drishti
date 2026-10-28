export default function Copilot() {
  return (
    <>
      <h1>8. Budget Copilot</h1>
      <p className="note" role="note">
        The chat assistant is Phase 11 and is not built yet. This page is where it will live: it will answer from the documents, the database and the models, with citations and
        simple charts, and refuse buy/sell requests.
      </p>
      <p>Until then, every number in the dashboard opens its source row, and the API documentation lists what can be queried: <a href="/docs">/docs</a>.</p>
      <label>
        Ask a question <input disabled placeholder="Available in Phase 11" style={{ width: "100%", maxWidth: 480 }} />
      </label>
    </>
  );
}
