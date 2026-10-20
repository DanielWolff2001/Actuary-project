"""Longevity risk in a Dutch pension portfolio: liability valuation."""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from pathlib import Path

# Path to data/processed, independent of where you run the script from
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CURVE_FILE = ROOT / "data" / "EIOPA_RFR_20260930" / "EIOPA_RFR_20260930_Term_Structures.xlsx"

VALUATION_YEAR = 2026
RETIREMENT_AGE = 68
MAX_AGE = 110


def load_rates():
    """Load central and simulated rates, convert m to q."""
    central = pd.concat(
        [pd.read_csv(DATA / f"central_rates_{sex}.csv") for sex in ("male", "female")],
        ignore_index=True,
    )
    sims = pd.concat(
        [pd.read_parquet(DATA / f"sim_rates_{sex}.parquet") for sex in ("male", "female")],
        ignore_index=True,
    )

    for df in (central, sims):
        df["Age"] = df["Age"].astype(int)
        df["Year"] = df["Year"].astype(int)
        df["q"] = 1 - np.exp(-df["m"])

    return central, sims


def to_array(df):
    """Long dataframe to array of m with shape (sex, sim, age, year)."""
    if "Sim" not in df.columns:
        df = df.assign(Sim=1)
    df = df.sort_values(["Sex", "Sim", "Age", "Year"])

    sexes = np.sort(df["Sex"].unique())
    sims = np.sort(df["Sim"].unique())
    ages = np.sort(df["Age"].unique())
    years = np.sort(df["Year"].unique())

    m = df["m"].to_numpy().reshape(len(sexes), len(sims), len(ages), len(years))
    return m, ages, years, sexes


def complete_table(df, fit_from=90, last_year=None):
    """Extend rates to MAX_AGE and beyond the last projection year.

    Returns q with shape (sex, sim, age, year), plus ages, years and sexes.
    """
    m, ages, years, sexes = to_array(df)
    n_sex, n_sim, _, n_year = m.shape

    # 1. Extrapolate log m linearly in age, fitted on ages fit_from..100
    fit_mask = ages >= fit_from
    log_m = np.log(m[:, :, fit_mask, :])
    y = np.moveaxis(log_m, 2, 0).reshape(fit_mask.sum(), -1)   # (fit ages, everything else)
    slope, intercept = np.polyfit(ages[fit_mask], y, 1)

    new_ages = np.arange(ages.max() + 1, MAX_AGE + 1)
    ext = intercept[None, :] + slope[None, :] * new_ages[:, None]
    ext = np.moveaxis(ext.reshape(len(new_ages), n_sex, n_sim, n_year), 0, 2)

    m = np.concatenate([m, np.exp(ext)], axis=2)
    ages = np.concatenate([ages, new_ages])

    # 2. Keep the last projected year constant until everyone has reached MAX_AGE
    if last_year is None:
        last_year = VALUATION_YEAR + (MAX_AGE - ages.min())
    n_extra = last_year - years.max()
    if n_extra > 0:
        m = np.pad(m, ((0, 0), (0, 0), (0, 0), (0, n_extra)), mode="edge")
        years = np.arange(years.min(), last_year + 1)

    # 3. Convert to q and close the table
    q = 1 - np.exp(-m)
    q[:, :, -1, :] = 1.0

    return q, ages, years, sexes


def generate_portfolio(n, seed=1):
    """Synthetic participants: id, age, sex, accrued pension, status."""
    rng = np.random.default_rng(seed)

    # --- Sex ---------------------------------------------------------------
    # TODO 1: draw n values from ["Female", "Male"], roughly 50/50.
    # Hint: rng.choice(..., size=n)
    sex = rng.choice(["Female", "Male"], size=n)

    # --- Age ---------------------------------------------------------------
    # Mix of actives and retirees, all aged 30 or older (your table starts at 30).
    ages_active = rng.integers(30, RETIREMENT_AGE, size=int(0.7 * n))

    # TODO 2: draw the remaining participants as retirees, aged
    # RETIREMENT_AGE up to about 95. Make sure the total is exactly n.
    ages_retired = rng.integers(RETIREMENT_AGE, 95, size=n - len(ages_active))

    age = np.concatenate([ages_active, ages_retired])

    # --- Status ------------------------------------------------------------
    # TODO 3: "active" if age < RETIREMENT_AGE, else "retired".
    # Hint: np.where
    status = np.where(age < RETIREMENT_AGE, "active", "retired")

    # --- Accrued pension (annual amount, euros) ----------------------------
    # Simple accrual model: pension = salary * accrual rate * years of service.
    accrual_rate = 0.0175
    salary = rng.lognormal(mean=np.log(45_000), sigma=0.3, size=n)
    pensionable = np.maximum(salary - 18_000, 0)

    # TODO 4: years of service. Assume people start working at 25.
    # For actives: years until now. For retirees: years until RETIREMENT_AGE.
    # Hint: np.minimum(age, RETIREMENT_AGE) - 25
    service = np.minimum(age, RETIREMENT_AGE) - 25

    pension = pensionable * accrual_rate * service

    portfolio = pd.DataFrame({
        "id": np.arange(n),
        "sex": sex,
        "age": age,
        "status": status,
        "pension": pension.round(2),
    })

    # TODO 5: save the portfolio to DATA / "portfolio.csv" (without the index).
    portfolio.to_csv(DATA / "portfolio.csv", index=False)

    return portfolio


def survival_probabilities(q, ages, years):
    """Survival along the generational diagonal for every starting age.

    Returns S with shape (sex, sim, start_age, t), where S[..., i, t] is the
    probability that someone aged ages[i] in VALUATION_YEAR is still alive
    t years later. S[..., i, 0] = 1.
    """
    n_age = len(ages)
    j0 = np.where(years == VALUATION_YEAR)[0][0]   # column of the valuation year
    i = np.arange(n_age)                            # starting age index
    t = np.arange(n_age)                            # years from now

    # TODO 1: index arrays for the diagonal, both with shape (n_age, n_age).
    # Starting at age index i in column j0, after t years you're at
    # age index i + t and year index j0 + t.
    # Hint: broadcasting, i[:, None] + t[None, :]
    age_idx = i[:, None] + t[None, :]
    year_idx = j0 + t[None, :]

    # TODO 2: once age_idx goes past the table, the person is dead.
    # Make a boolean mask `beyond` for that, then clip age_idx to n_age - 1
    # so the indexing below doesn't fail.
    beyond = age_idx >= n_age
    age_idx = np.clip(age_idx, 0, n_age - 1)

    # q along the diagonal, shape (sex, sim, start_age, t)
    q_diag = q[:, :, age_idx, year_idx]

    # TODO 3: set q_diag to 1 wherever `beyond` is True.
    q_diag[..., beyond] = 1

    # TODO 4: S_t = (1 - q_0) * (1 - q_1) * ... * (1 - q_{t-1}), with S_0 = 1.
    # Hint: np.cumprod over the last axis, then put a column of ones in front
    # and drop the last column (np.concatenate or np.pad).
    S = np.pad(np.cumprod(1 - q_diag, axis=-1), ((0, 0), (0, 0), (0, 0), (1, 0)), mode="constant", constant_values=1)
    S = S[..., :-1]

    return S


def cash_flows(portfolio, S, ages):
    """Expected pension payments per year, aggregated over the portfolio.

    Returns CF with shape (sim, t): the expected payment in year t from now.
    Payments are made at the start of each year to everyone alive and retired.
    """
    n_age = len(ages)
    n_t = S.shape[-1]
    t = np.arange(n_t)
    sex_order = ["Female", "Male"]   # same order as `sexes` from complete_table

    # TODO 1: total accrued pension per (sex, age) cell, shape (2, n_age).
    # Hint: portfolio.groupby(["sex", "age"])["pension"].sum() gives the totals.
    # Loop over the result and place each value in P:
    #   row = sex_order.index(sex), column = age - ages[0]
    P = np.zeros((2, n_age))
    for (sex, age), total in portfolio.groupby(["sex", "age"])["pension"].sum().items():
        row = sex_order.index(sex)
        column = age - ages[0]
        P[row, column] = total

    # TODO 2: payment indicator, shape (n_age, n_t).
    # 1 if someone aged ages[i] now is at least RETIREMENT_AGE after t years, else 0.
    # Hint: broadcasting, ages[:, None] + t[None, :]
    paying = (ages[:, None] + t[None, :] >= RETIREMENT_AGE).astype(int)

    # TODO 3: CF[sim, t] = sum over sex and age of P[sex, age] * S[sex, sim, age, t] * paying[age, t]
    # Hint: np.einsum("sa,snat,at->nt", P, S, paying)
    CF = np.einsum("sa,snat,at->nt", P, S, paying)

    return CF



def load_discount_curve(n_t, shift=0.0):
    """EIOPA risk-free curve to discount factors for t = 0, 1, ..., n_t - 1.

    `shift` adds a parallel shift to all rates (e.g. +0.01), for the interest shocks later.
    """
    # TODO 1: read the spot rates from the Excel file.
    # Open the file first and look at the layout: a few metadata rows on top,
    # maturities 1..150 in one column, one column per currency/country.
    # Hint: pd.read_excel(RAW / "...", sheet_name="RFR_spot_no_VA", ...)
    # with skiprows / usecols, or read everything and select afterwards.
    raw = pd.read_excel(CURVE_FILE, sheet_name="RFR_spot_no_VA", header=None)
    maturity = pd.to_numeric(raw.iloc[:, 1], errors="coerce")
    rows = maturity.between(1, 150) & (maturity % 1 == 0)
    rates = raw.loc[rows, 2].astype(float).to_numpy()

    rates = rates + shift

    # TODO 2: discount factors. Spot rates are annually compounded:
    #   DF(t) = (1 + r_t) ** (-t), with DF(0) = 1 (payment today isn't discounted).
    # You need t = 0, ..., n_t - 1, so the curve's maturities 1..n_t - 1 suffice.
    # Hint: build t = np.arange(1, n_t), then put a 1.0 in front with np.concatenate.
    discount_factors = np.concatenate((
        np.array([1.0]),
        (1 + rates[:n_t - 1]) ** -np.arange(1, n_t)
    ))

    return discount_factors


def bel_and_duration(cf, discount_factors):
    """Best-estimate liability and duration.

    cf has shape (sim, t), discount_factors has shape (t,).
    Returns BEL and duration, both with shape (sim,).
    """
    t = np.arange(cf.shape[1])

    # TODO 3: BEL = sum over t of CF_t * DF_t
    # Hint: a matrix-vector product, cf @ discount_factors
    bel = np.sum(cf * discount_factors, axis=1)

    # TODO 4: (Macaulay) duration = sum over t of t * CF_t * DF_t, divided by BEL.
    # It's the weighted average time of the payments, in years.
    duration = np.sum(t * cf * discount_factors, axis=1) / bel

    return bel, duration

def stochastic_bel(portfolio, sims, discount_factors):
    """BEL and duration per simulated mortality scenario.

    Runs the full chain (complete table -> survival -> cash flows -> BEL)
    on all scenarios at once. Returns bel and duration, both shape (n_sim,).
    """
    q_s, ages, years, _ = complete_table(sims)
    S_s = survival_probabilities(q_s, ages, years)
    CF_s = cash_flows(portfolio, S_s, ages)
    bel, duration = bel_and_duration(CF_s, discount_factors)
    return bel, duration


def summarise_bel(bel_sims, bel_central):
    """Print key statistics of the BEL distribution and plot a histogram."""
    q = np.quantile(bel_sims, [0.005, 0.05, 0.5, 0.95, 0.995])
    print(f"Central BEL:      {bel_central / 1e9:6.2f} bn")
    print(f"Mean of sims:     {bel_sims.mean() / 1e9:6.2f} bn")
    print(f"Std of sims:      {bel_sims.std() / 1e9:6.2f} bn")
    print(f"5% / 50% / 95%:   {q[1] / 1e9:6.2f} / {q[2] / 1e9:6.2f} / {q[3] / 1e9:6.2f} bn")
    print(f"99.5% quantile:   {q[4] / 1e9:6.2f} bn")
    print(f"99.5% - central:  {(q[4] - bel_central) / 1e6:6.0f} mln "
          f"({(q[4] / bel_central - 1) * 100:.1f}% of BEL)")

    plt.hist(bel_sims / 1e9, bins=50)
    plt.axvline(bel_central / 1e9, color="black", linestyle="--", label="Central")
    plt.axvline(q[4] / 1e9, color="red", linestyle="--", label="99.5%")
    plt.xlabel("BEL (EUR bn)"); plt.ylabel("Number of scenarios")
    plt.title("BEL across 1000 mortality scenarios")
    plt.legend()
    plt.show()


def bel_from_q(portfolio, q, ages, years, discount_factors):
    """Full chain for one mortality table: survival -> cash flows -> BEL."""
    S = survival_probabilities(q, ages, years)
    CF = cash_flows(portfolio, S, ages)
    bel, dur = bel_and_duration(CF, discount_factors)
    return bel[0], dur[0]


def shocks(portfolio, q, ages, years, discount_factors, longevity_shock=0.20, rate_shift=0.01):
    """Longevity (-20% q) and interest (+/-1%) shocks on the central BEL.

    Returns a table with BEL, duration and the change versus the base case.
    """
    n_t = len(discount_factors)

    # Longevity: all mortality rates permanently 20% lower (Solvency II standard formula)
    q_long = q * (1 - longevity_shock)
    q_long[:, :, -1, :] = 1.0          # keep the table closed at MAX_AGE

    scenarios = {
        "Base":             (q,      discount_factors),
        "Longevity -20% q": (q_long, discount_factors),
        "Rates -1%":        (q,      load_discount_curve(n_t, shift=-rate_shift)),
        "Rates +1%":        (q,      load_discount_curve(n_t, shift=+rate_shift)),
    }

    rows = {}
    for name, (q_scen, df_scen) in scenarios.items():
        bel, dur = bel_from_q(portfolio, q_scen, ages, years, df_scen)
        rows[name] = {"BEL (bn)": bel / 1e9, "Duration": dur}

    table = pd.DataFrame(rows).T
    base = table.loc["Base", "BEL (bn)"]
    table["Change (mln)"] = (table["BEL (bn)"] - base) * 1e3
    table["Change (%)"] = (table["BEL (bn)"] / base - 1) * 100

    print(table.round(2))
    return table


def export_for_excel(portfolio, q, S, ages, years, discount_factors, n=10, seed=2):
    """Small subset for the Excel reconciliation.

    Exports, per participant: the inputs (q along their diagonal, discount factors)
    and Python's results (cash flows, BEL), so Excel can rebuild and compare.
    """
    n_t = len(discount_factors)
    t = np.arange(n_t)
    j0 = np.where(years == VALUATION_YEAR)[0][0]
    sex_order = ["Female", "Male"]

    # Half actives, half retirees
    sample = (portfolio.groupby("status", group_keys=False)
                       .apply(lambda g: g.sample(n // 2, random_state=seed))
                       .reset_index(drop=True))

    q_table, cf_table, bels = {}, {}, []
    for _, p in sample.iterrows():
        s = sex_order.index(p.sex)
        i = p.age - ages[0]

        # q along this person's diagonal (1 once past MAX_AGE)
        age_path = p.age + t
        valid = age_path <= MAX_AGE
        q_path = np.ones(n_t)
        q_path[valid] = q[s, 0, i + t[valid], j0 + t[valid]]

        # Python's own calculation for this person
        paying = age_path >= RETIREMENT_AGE
        cf = p.pension * S[s, 0, i, :] * paying

        q_table[p.id] = q_path
        cf_table[p.id] = cf
        bels.append(cf @ discount_factors)

    sample["BEL_python"] = bels

    out = ROOT / "excel" / "python_export.xlsx"
    out.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(out) as writer:
        sample.to_excel(writer, sheet_name="Participants", index=False)
        pd.DataFrame(q_table, index=t).rename_axis("t").to_excel(writer, sheet_name="q_paths")
        pd.DataFrame({"t": t, "DF": discount_factors}).to_excel(writer, sheet_name="Discount", index=False)
        pd.DataFrame(cf_table, index=t).rename_axis("t").to_excel(writer, sheet_name="CF_python")

    print(f"Exported {len(sample)} participants to {out}")
    return sample


if __name__ == "__main__":
    # 1. Mortality: projected rates from R, extended to age 110 and beyond 2073
    central, sims = load_rates()
    q_c, ages, years, sexes = complete_table(central)

    # 2. Portfolio
    portfolio = generate_portfolio(100_000)

    # 3. Survival along the generational diagonal
    S_c = survival_probabilities(q_c, ages, years)

    # 4. Expected cash flows
    CF = cash_flows(portfolio, S_c, ages)
    print(CF.shape)                                   # expect (1, 81)

    retired_total = portfolio.loc[portfolio.status == "retired", "pension"].sum()
    print(f"CF at t=0: {CF[0, 0]:,.0f}   retiree total: {retired_total:,.0f}")

    plt.plot(np.arange(CF.shape[1]), CF[0] / 1e6)
    plt.xlabel("Years from now"); plt.ylabel("Expected payments (EUR mln)")
    plt.title("Projected pension cash flows")
    plt.show()

    DF = load_discount_curve(CF.shape[1])
    bel, dur = bel_and_duration(CF, DF)
    print(f"Undiscounted: {CF[0].sum()/1e9:.2f} bn")
    print(f"BEL: {bel[0]/1e9:.2f} bn, duration: {dur[0]:.1f} years")

    bel_s, dur_s = stochastic_bel(portfolio, sims, DF)
    summarise_bel(bel_s, bel[0])

    shock_table = shocks(portfolio, q_c, ages, years, DF)
    shock_table.to_csv(DATA / "shock_results.csv")

    export_for_excel(portfolio, q_c, S_c, ages, years, DF)