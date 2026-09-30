import { TIME_ZONE } from "./config";

const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE });
const dayFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: TIME_ZONE });
const fullFmt = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE, timeZoneName: "short",
});

/** Epoch seconds, a Date, or an ISO string. */
export type When = number | string | Date;
const toDate = (x: When) => (typeof x === "number" ? new Date(x * 1000) : new Date(x));

export const hm = (x: When) => timeFmt.format(toDate(x));
export const day = (x: When) => dayFmt.format(toDate(x));
export const full = (x: When) => fullFmt.format(toDate(x));
export const epoch = (x: When) => toDate(x).getTime() / 1000;
export const pct = (p: number, digits = 0) => `${(p * 100).toFixed(digits)}%`;
export const shortFingerprint = (fp: string) => (fp.length > 23 ? `${fp.slice(0, 19)}…` : fp);

export const SOURCE_TYPE: Record<string, string> = {
  cso: "sewer overflow", storm_outfall: "storm outfall", misconnection: "misconnection",
  industrial: "industrial",
};
export const PATHWAY: Record<string, string> = {
  recreation: "recreation", animal_contact: "animal contact", floodwater: "floodwater",
  irrigation: "irrigation",
};
export const METHOD: Record<string, string> = {
  citizen_visual_olfactory: "Citizen report", citizen_freetext: "Citizen report",
  test_strip: "Test strip", field_test: "Field test", lab_ecoli: "Lab E. coli",
  sensor_turbidity: "Sensor", overflow_telemetry: "Overflow telemetry",
};
