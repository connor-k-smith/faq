import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { landingFixture, projectFixture } from "./fixtures";
import { mockApi } from "./mockApi";
import { renderApp } from "./renderApp";

describe("project workspace", () => {
  beforeEach(() => {
    const project = projectFixture();
    const landing = landingFixture();
    mockApi(async (input, init) => {
      if (init?.method === "POST") {
        return Response.json(
          { detail: "an active Initiative already uses that name" },
          { status: 409 },
        );
      }
      return Response.json(
        String(input) === "/api/projects" ? [project] : landing,
      );
    });
  });

  it("presents member Projects grouped by Initiative", async () => {
    renderApp();

    expect(
      await screen.findByRole("heading", { name: "Atlas" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Active Initiatives" }),
    ).toHaveTextContent("Pool matching");
    expect(screen.getByText("Confirm desired state")).toBeInTheDocument();
    expect(screen.getByLabelText("Project")).toHaveValue("project-1");
  });

  it("surfaces an active-name conflict inline", async () => {
    renderApp();
    await screen.findByRole("heading", { name: "Atlas" });
    fireEvent.click(screen.getByRole("button", { name: "+ New Initiative" }));
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Pool matching" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Initiative" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "already uses that name",
    );
  });

  it("links draft history back to authoring", async () => {
    const project = projectFixture();
    const landing = landingFixture();
    landing.initiatives[0].asks[0].status = "draft";
    mockApi(async (input) =>
      Response.json(String(input) === "/api/projects" ? [project] : landing),
    );
    renderApp();

    expect(
      await screen.findByRole("link", { name: /Confirm desired state/ }),
    ).toHaveAttribute("href", "/a/ask-1/edit");
  });

  it("keeps Initiative edits open when a duplicate name conflicts", async () => {
    const project = projectFixture();
    const landing = landingFixture();
    mockApi(async (input, init) => {
      if (init?.method === "PUT") {
        return Response.json(
          { detail: "an active Initiative already uses that name" },
          { status: 409 },
        );
      }
      return Response.json(
        String(input) === "/api/projects" ? [project] : landing,
      );
    });
    renderApp();
    await screen.findByRole("heading", { name: "Atlas" });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Existing Initiative" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Initiative" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "already uses that name",
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Existing Initiative");
  });
});
