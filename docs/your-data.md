# Using your own data

OpenClock reads files you export from Garmin Connect and from the Health app. Keep them in a folder **outside the repository**, for example `~/openclock-data` (Windows: `C:\Users\you\openclock-data`), so they are never committed and are not removed when a desktop session cleans up its worktree.

## Garmin

Any of these work. Put them in the folder as you downloaded them:

| What you download | How (Garmin Connect website) | File |
|---|---|---|
| One activity | Open the activity → ⚙️ → **Export Original** | `.zip` with one `.fit` inside |
| One activity, unzipped | Same, then extract | `.fit` |
| Everything | Account → Data Management → **Export Your Data** (Garmin emails a link) | a large `.zip` with more zips inside |

Garmin's menus change from time to time. Look for "Export Original" on an activity, or for the account data export.

OpenClock opens zips by itself, including one level of zips inside a zip, and reads every `.fit` it finds. The same activity as a loose `.fit` and inside a zip counts once. Members larger than 50 MB are skipped, with a warning.

## Apple Watch (Health app)

On the iPhone: **Health** → your profile picture → **Export All Health Data**. Send `export.zip` to your computer and drop it in the folder; there is no need to unzip it. Real exports can be hundreds of MB, and OpenClock streams them.

## Goals (optional)

Copy [`samples/goals.toml`](../samples/goals.toml) into the folder and edit the targets. See [docs/mcp.md](mcp.md#goal_progress) for the fields.

## Check the folder

```bash
openclock check --data-dir ~/openclock-data --timezone America/Sao_Paulo
```

The command shows, for each source, how many workouts it read and which dates they cover. It also lists:

- workouts without distance or duration;
- **possible duplicates** across devices (the same run recorded by both watches, or synced from Garmin into the Health app);
- files that failed to import, with the reason;
- whether `goals.toml` is valid.

Fix anything it reports, then point Mode A (`--data-dir`) or the bot (`data_dir` in `telegram.toml` / `whatsapp.toml`) at the folder.

## Privacy

These files contain your health data and, for GPS activities, your routes. OpenClock reads only the summary of each workout (start, duration, distance, sport), but the files themselves include more. Keep the folder private, never attach these files to issues, and delete them when you stop using OpenClock.
