import { describe, expect, it } from "vitest";

import {
  draftFixture,
  landingFixture,
  projectFixture,
  resultsFixture,
} from "./fixtures";

describe("feature fixture factories", () => {
  it("provide representative shared API payloads", () => {
    expect(projectFixture().name).toBe("Atlas");
    expect(landingFixture().initiatives).toHaveLength(1);
    expect(draftFixture().questions).toHaveLength(1);
    expect(resultsFixture().stakeholders).toHaveLength(2);
  });
});
