# Deploying MedCard AI (free)

## 1. Free Postgres on Neon (10 minutes, keeps data forever)

Render's free servers wipe their disk whenever they restart, so the data lives in a free Neon database instead.

1. Go to **neon.tech**, sign up with GitHub, click **Create project** (any name, region **AWS Asia Pacific (Singapore)**).
2. On the dashboard, click **Connect**, choose **Python / psycopg2**, and copy the connection string. It looks like:
   `postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
3. Change the start to `postgresql+psycopg2://` (keep everything else). That is your `DATABASE_URL`.

Skipping Neon still works: the app falls back to SQLite and re-creates the demo data on every restart. Fine for a quick demo, but new sign-ups disappear.

## 2. Web service on Render

1. **New + → Web Service**, then pick the `medcard` repo. Language: **Docker**. Region: **Singapore**. Instance: **Free**.
2. **Environment variables:**
   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the Neon string from step 1 |
   | `JWT_SECRET` | any long random text (click **Generate**) |
   | `ANTHROPIC_API_KEY` *or* `OPENAI_API_KEY` | optional, enables live AI |
3. **Deploy Web Service.** The first build takes a few minutes. Tables and demo data are created automatically on first start.
4. Open the URL, log in as patient `2507070000057` / `Demo@123`, open **My E-Card** and scan the QR with your phone.

## 3. Update your project links

Put the Render URL in the README's **Live demo** line and in the GitHub repo's **About → Website** box.

## Updating later

Push to `main` and Render redeploys automatically. Data in Neon is untouched.
