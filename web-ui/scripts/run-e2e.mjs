import { readFile, writeFile } from "node:fs/promises"
import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"

const trackedConfig = await Promise.all(
  ["next-env.d.ts", "tsconfig.json"].map(async (name) => {
    const path = fileURLToPath(new URL(`../${name}`, import.meta.url))
    return { path, original: await readFile(path) }
  }),
)
const command = process.platform === "win32" ? "pnpm.cmd" : "pnpm"

let exitCode = 1
try {
  exitCode = await new Promise((resolve, reject) => {
    const child = spawn(command, ["exec", "playwright", "test"], {
      stdio: "inherit",
    })
    child.once("error", reject)
    child.once("exit", (code) => resolve(code ?? 1))
  })
} finally {
  await Promise.all(
    trackedConfig.map(({ path, original }) => writeFile(path, original)),
  )
}

process.exitCode = exitCode
