# Project setup

This is a food photography gallery with a Python standard-library API server.

## Run on Replit

Start the `Start application` workflow. It runs the project on `0.0.0.0:5000` with:

```sh
python3 server.py
```

The server uses Python's standard library and does not require a package-install step.
`CEREBRAS_SECRET` is optional; without it, community notes use a local rating summary.
Reviews require both a 1–5 star rating and a non-empty comment. Each food item's
saved community note is regenerated only when a new review is posted; normal
gallery reads use the saved note without another AI request. Reviews return
immediately after they are saved while the community note updates in the
background.