import os
import math
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.ensemble import HistGradientBoostingRegressor

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ML_DIR = os.path.dirname(os.path.abspath(__file__))


def load_data():
    sales = pd.read_csv(os.path.join(DATA_DIR, "sales_history.csv"))
    lead = pd.read_csv(os.path.join(DATA_DIR, "lead_times.csv"))
    promo = pd.read_csv(os.path.join(DATA_DIR, "promo_calendar.csv"))
    fest = pd.read_csv(os.path.join(DATA_DIR, "festival_calendar.csv"))
    catalogue = pd.read_csv(os.path.join(DATA_DIR, "catalogue.csv"))

    sales["week_start"] = pd.to_datetime(sales["week_start"])
    promo["week_start"] = pd.to_datetime(promo["week_start"])
    fest["date"] = pd.to_datetime(fest["date"])

    return sales, lead, promo, fest, catalogue


def get_diwali_date(dt, fest_df):
    year = dt.year
    match = fest_df[fest_df["date"].dt.year == year]
    if not match.empty:
        return match.iloc[0]["date"]
    return datetime(year, 11, 1)


def build_feature_matrix():
    sales, lead, promo, fest, catalogue = load_data()
    target_skus = sorted(lead["sku"].unique())

    # Pre-index sales into dict for fast lookup
    sales_dict = {}
    promo_dict = {}
    for _, r in sales.iterrows():
        sales_dict[(r["sku"], r["week_start"])] = float(r["units_sold"])
        promo_dict[(r["sku"], r["week_start"])] = int(r["promo_flag"])

    for _, r in promo.iterrows():
        promo_dict[(r["sku"], r["week_start"])] = int(r["promo_flag"])

    cat_map = catalogue.set_index("sku")

    all_weeks = sorted(sales["week_start"].unique())
    sku_weeks = {sku: sorted([w for (s, w) in sales_dict.keys() if s == sku]) for sku in target_skus}

    feature_cols = [
        "horizon", "last_val", "mean_4", "mean_8", "mean_12",
        "std_4", "std_12", "swly", "promo_flag", "weeks_to_diwali",
        "week_of_year", "month", "price"
    ]

    def extract_features(origin_dt, horizon_weeks):
        records = []
        for sku in target_skus:
            past_w = [w for w in sku_weeks[sku] if w <= origin_dt]
            if not past_w:
                continue

            past_sales = [sales_dict[(sku, w)] for w in past_w]
            last_val = past_sales[-1]
            mean_4 = float(np.mean(past_sales[-4:]))
            mean_8 = float(np.mean(past_sales[-8:]))
            mean_12 = float(np.mean(past_sales[-12:]))

            std_4 = float(np.std(past_sales[-4:], ddof=1)) if len(past_sales) >= 2 else 0.0
            std_12 = float(np.std(past_sales[-12:], ddof=1)) if len(past_sales) >= 2 else 0.0
            if math.isnan(std_4):
                std_4 = 0.0
            if math.isnan(std_12):
                std_12 = 0.0

            price = float(cat_map.loc[sku, "price"]) if sku in cat_map.index else 0.0

            for h in range(1, horizon_weeks + 1):
                target_w = origin_dt + timedelta(weeks=h)
                promo_flag = promo_dict.get((sku, target_w), 0)

                # Same week last year (52 weeks prior)
                swly_w = target_w - timedelta(weeks=52)
                swly = sales_dict.get((sku, swly_w), mean_4)

                diwali_dt = get_diwali_date(target_w, fest)
                weeks_to_diwali = (diwali_dt - target_w).days / 7.0

                records.append({
                    "sku": sku,
                    "target_week": target_w,
                    "horizon": h,
                    "last_val": last_val,
                    "mean_4": mean_4,
                    "mean_8": mean_8,
                    "mean_12": mean_12,
                    "std_4": std_4,
                    "std_12": std_12,
                    "swly": swly,
                    "promo_flag": promo_flag,
                    "weeks_to_diwali": weeks_to_diwali,
                    "week_of_year": target_w.isocalendar().week,
                    "month": target_w.month,
                    "price": price,
                })
        return pd.DataFrame(records)

    # Rolling origin validation splits
    val_origins = [
        pd.to_datetime("2026-06-01"),
        pd.to_datetime("2026-06-29"),
        pd.to_datetime("2026-07-27"),
        pd.to_datetime("2026-08-24"),
    ]

    results = {
        "Last-Value": {"errors": [], "actuals": []},
        "Recent-Average (4w)": {"errors": [], "actuals": []},
        "Same-Week-Last-Year": {"errors": [], "actuals": []},
        "HistGradientBoosting": {"errors": [], "actuals": []},
    }

    print("Running chronological rolling-origin validation...")
    for origin in val_origins:
        # Build training data strictly before this origin
        train_origins = [w for w in all_weeks if pd.to_datetime("2025-09-01") <= w < origin]
        train_dfs = [extract_features(t_orig, 4) for t_orig in train_origins]
        df_train = pd.concat(train_dfs, ignore_index=True)

        # Match actuals
        y_train = []
        keep_indices = []
        for idx, r in df_train.iterrows():
            act = sales_dict.get((r["sku"], r["target_week"]))
            if act is not None:
                y_train.append(act)
                keep_indices.append(idx)

        df_train_sub = df_train.loc[keep_indices]
        y_train_arr = np.array(y_train)

        # Train ML model
        model = HistGradientBoostingRegressor(max_iter=150, min_samples_leaf=10, random_state=42)
        model.fit(df_train_sub[feature_cols], y_train_arr)

        # Evaluate on validation origin
        val_df = extract_features(origin, 4)
        for _, r in val_df.iterrows():
            act = sales_dict.get((r["sku"], r["target_week"]))
            if act is None:
                continue

            # Baselines
            pred_lv = max(0.0, float(r["last_val"]))
            pred_ra = max(0.0, float(r["mean_4"]))
            pred_sw = max(0.0, float(r["swly"]))

            # ML model
            x_row = pd.DataFrame([r[feature_cols]])
            pred_ml = max(0.0, float(model.predict(x_row)[0]))

            results["Last-Value"]["errors"].append(abs(act - pred_lv))
            results["Last-Value"]["actuals"].append(act)

            results["Recent-Average (4w)"]["errors"].append(abs(act - pred_ra))
            results["Recent-Average (4w)"]["actuals"].append(act)

            results["Same-Week-Last-Year"]["errors"].append(abs(act - pred_sw))
            results["Same-Week-Last-Year"]["actuals"].append(act)

            results["HistGradientBoosting"]["errors"].append(abs(act - pred_ml))
            results["HistGradientBoosting"]["actuals"].append(act)

    print("\n================== BACKTESTING METRICS ==================")
    metrics_summary = {}
    for name, m in results.items():
        mae = float(np.mean(m["errors"]))
        wape = float(np.sum(m["errors"]) / np.sum(m["actuals"]) * 100.0)
        metrics_summary[name] = {"MAE": mae, "WAPE": wape}
        print(f"{name:25s} | MAE: {mae:6.2f} | WAPE: {wape:6.2f}%")
    print("=========================================================\n")

    # Fit final model on all data up to 2026-09-21
    final_origin = pd.to_datetime("2026-09-21")
    train_origins_all = [w for w in all_weeks if pd.to_datetime("2025-06-01") <= w < final_origin]
    train_dfs_all = [extract_features(t_orig, 4) for t_orig in train_origins_all]
    df_train_all = pd.concat(train_dfs_all, ignore_index=True)

    y_train_final = []
    keep_indices_final = []
    for idx, r in df_train_all.iterrows():
        act = sales_dict.get((r["sku"], r["target_week"]))
        if act is not None:
            y_train_final.append(act)
            keep_indices_final.append(idx)

    final_model = HistGradientBoostingRegressor(max_iter=150, min_samples_leaf=10, random_state=42)
    final_model.fit(df_train_all.loc[keep_indices_final, feature_cols], np.array(y_train_final))

    # Forecast target 4 weeks
    target_df = extract_features(final_origin, 4)
    preds = final_model.predict(target_df[feature_cols])

    forecast_rows = []
    for idx, r in target_df.iterrows():
        val = max(0.0, round(float(preds[idx]), 1))
        # Ensure that newly launched SKUs with zero or low prediction default to recent average
        if val == 0 and r["mean_4"] > 0:
            val = round(float(r["mean_4"]), 1)
        forecast_rows.append({
            "sku": r["sku"],
            "week_start": r["target_week"].strftime("%Y-%m-%d"),
            "forecast_units": val,
        })

    df_forecast = pd.DataFrame(forecast_rows).sort_values(["sku", "week_start"])
    out_csv = os.path.join(ML_DIR, "forecast.csv")
    df_forecast.to_csv(out_csv, index=False)
    print(f"Generated forecast.csv at {out_csv} with {len(df_forecast)} rows.")

    return metrics_summary


if __name__ == "__main__":
    build_feature_matrix()
