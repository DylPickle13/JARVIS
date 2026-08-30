export function truncate(text: string, max = 12_000): string {
  return text.length > max ? `${text.slice(0, max)}\n… truncated …` : text;
}
