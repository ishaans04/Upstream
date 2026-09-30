import type { Metadata } from "next";
import { MissionsHome } from "@/components/MissionsHome";

export const metadata: Metadata = { title: "Missions" };

export default function MissionsPage() {
  return (
    <section className="page" aria-labelledby="missionsTitle">
      <div className="page-head"><div>
        <div className="eyebrow">Volunteer mission app</div>
        <h1 id="missionsTitle">One task, one place, one result</h1>
        <p className="desc">Works without signal: a reading is saved on the phone with the time it was taken, and sent when the phone is
          back online.</p>
      </div></div>
      <MissionsHome />
    </section>
  );
}
