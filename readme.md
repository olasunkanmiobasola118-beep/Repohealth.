RepoHealth is an open-source tool for checking the health of public GitHub repositories. It reads repository data through GitHub's public API and never runs code from the repositories it scans.

Report types

Every report separates three kinds of output:

Objective checks: pass/fail results based on facts in the repository, such as whether a README, license, or CI configuration exists.
Heuristic warnings: signals that may indicate a problem but need human judgment to interpret.
AI-generated suggestions: optional recommendations produced by an open-weight model. These are suggestions, not verified findings.

A clean report does not prove a project is secure. RepoHealth is a starting point for review, not a substitute for a security audit.

Tech stack
Backend: Python, Flask
Frontend: HTML, CSS, vanilla JavaScript, Bootstrap 5, Chart.js
Optional AI: open-weight models through Ollama
Tests: pytest
Getting started

These steps assume Python 3 and Git are installed.

bash
git clone https://github.com/<your-username>/repohealth.git
cd repohealth
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py

Then open the local address printed in the terminal (usually http://127.0.0.1:5000).

Run the tests with:

bash
pytest
Contributing

Contributions are welcome. Areas where help is especially useful:

Frontend: layout, accessibility, and design
Documentation: tutorials, examples, and translations
Testing: tests for scanner and scoring rules
Scanner rules: proposing and implementing new checks
AI providers: support for other open-weight model runtimes

Contribution guidelines will be added to the repository before it is opened to the community.

License

RepoHealth is licensed under the Apache License 2.0. See LICENSE for details.
