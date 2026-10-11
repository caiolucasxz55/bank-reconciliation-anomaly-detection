import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NavBar } from "./NavBar";

const pathname = vi.hoisted(() => ({ current: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

describe("NavBar", () => {
  afterEach(cleanup);

  it("marks the current page", () => {
    pathname.current = "/importar";
    render(<NavBar />);
    const current = screen.getByRole("link", { name: "Importar dados" });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Transações" }).getAttribute("aria-current")).toBeNull();
  });

  it("links both pages", () => {
    pathname.current = "/";
    render(<NavBar />);
    expect(screen.getByRole("link", { name: "Transações" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("link", { name: "Importar dados" }).getAttribute("href")).toBe(
      "/importar",
    );
  });

  it.each(["/importar/", "/importar/historico"])("keeps %s under its section", (path) => {
    pathname.current = path;
    render(<NavBar />);
    const link = screen.getByRole("link", { name: "Importar dados" });
    expect(link.getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Transações" }).getAttribute("aria-current")).toBeNull();
  });
});
