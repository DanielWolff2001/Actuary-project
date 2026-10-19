# Actuary-project
trying out a project to train my ability to work in an actuarial field.

Data - Deaths and Exposures from HMD year 1850-2023, age 0-110+, sex male/female

R – mortality modelling: Fit Lee-Carter (and maybe Cairns-Blake-Dowd) on Dutch data from the Human Mortality Database using StMoMo. Project mortality 50+ years ahead with uncertainty bands, and compare your results with the AG2024 projection table.

Python – liability engine: Generate a synthetic pension portfolio (ages, accrued pensions, gender). Project cash flows, discount with the EIOPA risk-free curve, and calculate the best-estimate liability and duration. Add stochastic simulation from your R scenarios, plus a Solvency II longevity shock (20% permanent drop in mortality) to get a capital-style number.

Excel – the reviewable model: Build a clean deterministic version for a subset of the portfolio. Include named ranges, an assumptions sheet, a sensitivity table (interest ±1%, longevity shock), and a small dashboard. Reconcile it with Python. That reconciliation step is exactly what actuarial trainees do.

Report: A 4–6 page report covering method, results, limitations, and what I'd do next.

Order of project:
1. Data-cleaning-MHD.Rmd <- loads HMD data, filters on age 30-100, year 1990-2023 and fits Lee-Carter and Renshaw-Haberman. Returns forecasts and central rates.
2. activate venv.