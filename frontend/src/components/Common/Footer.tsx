

export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t py-4 px-6">
      <div className="flex flex-col items-center gap-4 sm:flex-row justify-center">
        <p className="text-muted-foreground text-sm">
          Conduit - {currentYear}
        </p>
      </div>
    </footer>
  )
}
