"use client";
import Link from "next/link";
import { getMission } from "@/lib/api";
import { MissionFlow } from "./MissionFlow";
import { useVolunteer } from "./MissionsHome";
import { LoadError, Loading } from "./States";
import { useLoad } from "./useLoad";

export function MissionPage({ id }: { id: string }) {
  const [volunteer] = useVolunteer();
  const m = useLoad(() => getMission(id), [id]);
  if (m.error) return <LoadError what={`mission ${id}`} error={m.error} />;
  if (!m.data) return <Loading what="the mission" />;
  return (
    <section className="page" aria-labelledby="missionTitle">
      <div className="page-head"><div>
        <div className="eyebrow">Mission {m.data.mission_id}</div>
        <h1 id="missionTitle" className="sr-only">Mission {m.data.mission_id}</h1>
        <Link href="/missions" className="note">← All my missions</Link>
      </div></div>
      {volunteer
        ? <MissionFlow mission={m.data} volunteerId={volunteer} />
        : <p className="note">Open <Link href="/missions">Missions</Link> and enter your volunteer id first.</p>}
    </section>
  );
}
