import { useEffect, useState } from "react";
import { api } from "./api";
import { go } from "./App";
import { useText } from "./prefs";
import type { Progress } from "./types";

export function ProgressCard({value}: {value: Progress}) {
  const t = useText();
  return <section className="progress-card"><div className="progress-heading"><div><p className="eyebrow">{t("YOUR NEXT CHAPTER","ඊළඟ පියවර")}</p><h2>{value.enabled ? `${t("Level","Level")} ${value.level} · ${value.xp} XP` : t("Your reading progress","ඔයාගේ කියවීමේ ප්‍රගතිය")}</h2></div>{value.enabled && <span className="level-orb">{value.level}</span>}</div>
    {value.enabled && <><div className="goal-track"><span style={{width: `${value.xp % 100}%`}} /></div><p className="small">{value.streak} {t("day streak","දවස් streak")} · {100 - value.xp % 100} XP {t("to next level","ඊළඟ level එකට")}</p></>}
    <div className="daily-goals"><span>{t("Read","කියවීම")} <b>{value.reading_minutes}/{value.reading_goal}</b> min</span><span>{t("Answer","පිළිතුරු")} <b>{value.answers}/{value.question_goal}</b></span></div>
    {value.enabled && <p className="small">{value.challenge_complete ? t("Daily challenge complete · +20 XP","Daily challenge එක ඉවරයි · +20 XP") : t("Complete both goals for the daily challenge.","Daily challenge එකට goals දෙකම සම්පූර්ණ කරන්න.")}</p>}
    {value.enabled&&!!value.badges.length && <div className="actions">{value.badges.map((b) => <span className="chip" key={b}>✦ {b}</span>)}</div>}
  </section>;
}
export default function ProgressPage() {
  const t = useText();
  const [value,setValue] = useState<Progress | null>(null), [error,setError] = useState("");
  useEffect(() => {api.progress().then(setValue).catch((e) => setError(e.message));},[]);
  return <main className="library"><header className="page-head"><button className="act" onClick={() => go("/")}>← {t("Library","පොත්")}</button><h1>{t("Progress","ප්‍රගතිය")}</h1></header>{error && <p role="alert">{error}</p>}{value && <><ProgressCard value={value}/><section className="settings-card"><h2>{t("Reading & study history","කියවීම් සහ study ඉතිහාසය")}</h2>{value.history.length ? <div className="tablewrap"><table><thead><tr><th>Date</th><th>Minutes</th><th>Answers</th>{value.enabled && <th>XP</th>}</tr></thead><tbody>{value.history.map((r) => <tr key={r.day}><td>{r.day}</td><td>{r.reading_minutes}</td><td>{r.answers}</td>{value.enabled && <td>{r.xp}</td>}</tr>)}</tbody></table></div> : <p className="small">{t("Start reading to build your history.","කියවන්න පටන් ගත්තම මෙතන ප්‍රගතිය පෙන්වයි.")}</p>}</section></>}</main>;
}
