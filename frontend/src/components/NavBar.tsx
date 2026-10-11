"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import styles from "./nav.module.css";

const LINKS = [
  { href: "/", label: "Transações" },
  { href: "/importar", label: "Importar dados" },
];

/** "/importar/" and "/importar/historico" belong to "/importar"; "/" only to itself. */
function isCurrent(pathname: string, href: string): boolean {
  const path = pathname.replace(/\/+$/, "") || "/";
  return href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`);
}

export function NavBar() {
  const pathname = usePathname();
  return (
    <nav className={styles.nav} aria-label="Principal">
      <div className={styles.inner}>
        <span className={styles.brand}>Conciliação bancária</span>
        <ul className={styles.links}>
          {LINKS.map((link) => {
            const current = isCurrent(pathname, link.href);
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className={current ? styles.active : undefined}
                  aria-current={current ? "page" : undefined}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
