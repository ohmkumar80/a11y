"use client";

export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <head><title>Something went wrong</title></head>
      <body style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", color: "#14181d", background: "#fff" }}>
        <main>
          <h1>Something went wrong</h1>
          <p>The application could not load. Try again.</p>
          <button type="button" onClick={reset} style={{ minHeight: 44, padding: "0 16px", font: "inherit" }}>Try again</button>
        </main>
      </body>
    </html>
  );
}
