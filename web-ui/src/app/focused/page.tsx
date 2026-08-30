import { FocusedWorkspace } from "@/features/focused"

type FocusedPageProps = {
  searchParams: Promise<{ demo?: string | string[] }>
}

export default async function FocusedPage({ searchParams }: FocusedPageProps) {
  const params = await searchParams
  return <FocusedWorkspace demo={params.demo === "1"} />
}
