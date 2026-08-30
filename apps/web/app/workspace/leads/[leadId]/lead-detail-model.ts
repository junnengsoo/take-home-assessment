export type Attorney = {
  id: string;
  email: string;
  displayName: string;
};

export type Status = "PENDING" | "REACHED_OUT";

export type LeadDetail = {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  status: Status;
  version: number;
  createdAt: string;
  assignedAttorney: Attorney | null;
  resume: {
    id: string;
    originalFilename: string;
    contentType: string;
    byteSize: number;
    createdAt: string;
    previewable: boolean;
  };
  statusChanges: Array<{
    id: string;
    status: Status;
    actor:
      | { type: "SYSTEM" }
      | {
          type: "ATTORNEY";
          attorney: Attorney;
        };
    createdAt: string;
  }>;
};

export const STATUS_LABELS = {
  PENDING: "Pending",
  REACHED_OUT: "Reached out"
};

export function requestId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}`;
}
