import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

import { truncate } from "./lib/text";

const DEFAULT_FOLDER = "Notes";
const DEFAULT_SEARCH_LIMIT = 10;
const MAX_SEARCH_LIMIT = 50;
const APPLE_SCRIPT_TIMEOUT_MS = 45_000;

const APPLE_NOTES_SCRIPT = String.raw`
on replaceText(findText, replaceWith, subjectText)
  set savedDelimiters to AppleScript's text item delimiters
  set AppleScript's text item delimiters to findText
  set textItems to every text item of subjectText
  set AppleScript's text item delimiters to replaceWith
  set resultText to textItems as text
  set AppleScript's text item delimiters to savedDelimiters
  return resultText
end replaceText

on joinList(listValue, delimiter)
  set savedDelimiters to AppleScript's text item delimiters
  set AppleScript's text item delimiters to delimiter
  set resultText to listValue as text
  set AppleScript's text item delimiters to savedDelimiters
  return resultText
end joinList

on jsonEscape(value)
  set s to value as text
  set s to my replaceText("\\", "\\\\", s)
  set s to my replaceText("\"", "\\\"", s)
  set s to my replaceText(return, "\\n", s)
  set s to my replaceText(linefeed, "\\n", s)
  set s to my replaceText(tab, "\\t", s)
  return s
end jsonEscape

on shortText(value, maxLength)
  set s to value as text
  if (count of s) is greater than maxLength then return text 1 thru maxLength of s
  return s
end shortText

on trimTrailingNewlines(value)
  set s to value as text
  repeat while (count of s) is greater than 0
    set lastCharacter to character (count of s) of s
    if lastCharacter is return or lastCharacter is linefeed then
      if (count of s) is 1 then
        set s to ""
      else
        set s to text 1 thru ((count of s) - 1) of s
      end if
    else
      exit repeat
    end if
  end repeat
  return s
end trimTrailingNewlines

on pad2(value)
  set s to (value as integer) as text
  if (count of s) is 1 then set s to "0" & s
  return s
end pad2

on isoDate(value)
  try
    return ((year of value as integer) as text) & "-" & my pad2(month of value as integer) & "-" & my pad2(day of value as integer) & "T" & my pad2(hours of value as integer) & ":" & my pad2(minutes of value as integer) & ":" & my pad2(seconds of value as integer)
  on error
    return ""
  end try
end isoDate

on htmlEscape(value)
  set s to value as text
  set s to my replaceText("&", "&amp;", s)
  set s to my replaceText("<", "&lt;", s)
  set s to my replaceText(">", "&gt;", s)
  set s to my replaceText("\"", "&quot;", s)
  return s
end htmlEscape

on htmlFromPlaintext(value)
  set lineList to paragraphs of (value as text)
  if (count of lineList) is 0 then set lineList to {""}
  set htmlLines to {}
  repeat with oneLine in lineList
    set lineText to contents of oneLine as text
    set end of htmlLines to "<div>" & my htmlEscape(lineText) & "</div>"
  end repeat
  return my joinList(htmlLines, return)
end htmlFromPlaintext

on argumentAt(argv, indexNumber)
  if (count of argv) is less than indexNumber then return ""
  return item indexNumber of argv as text
end argumentAt

on positiveInteger(value, fallback)
  try
    set n to value as integer
    if n is less than 1 then return fallback
    return n
  on error
    return fallback
  end try
end positiveInteger

on folderNameMatches(folderName, requestedFolder)
  if requestedFolder is "" then return true
  ignoring case
    return folderName is requestedFolder
  end ignoring
end folderNameMatches

on addFolderTree(theFolder, folderList)
  tell application "Notes"
    set currentFolderName to (name of theFolder) as text
    if currentFolderName is not "Recently Deleted" then
      set end of folderList to theFolder
      repeat with childFolderRef in (every folder of theFolder)
        set folderList to my addFolderTree(contents of childFolderRef, folderList)
      end repeat
    end if
  end tell
  return folderList
end addFolderTree

on collectFolders()
  tell application "Notes"
    set noteAccount to account "iCloud"
    set folderList to {}
    repeat with topFolderRef in (every folder of noteAccount)
      set folderList to my addFolderTree(contents of topFolderRef, folderList)
    end repeat
  end tell
  return folderList
end collectFolders

on findFolder(folderList, requestedFolder)
  set targetName to requestedFolder
  if targetName is "" then set targetName to "Notes"
  set matches to {}
  repeat with folderRef in folderList
    set theFolder to contents of folderRef
    tell application "Notes"
      set currentFolderName to (name of theFolder) as text
    end tell
    if my folderNameMatches(currentFolderName, targetName) then set end of matches to {theFolder, currentFolderName}
  end repeat
  if (count of matches) is 0 then error "No iCloud Notes folder named '" & targetName & "' was found."
  if (count of matches) is greater than 1 then error "More than one iCloud Notes folder is named '" & targetName & "'; use a unique folder name."
  return item 1 of matches
end findFolder

on resolveNote(folderList, requestedId, requestedTitle, requestedFolder)
  if requestedId is "" and requestedTitle is "" then error "A note id or title is required."
  set matches to {}
  repeat with folderRef in folderList
    set theFolder to contents of folderRef
    tell application "Notes"
      set currentFolderName to (name of theFolder) as text
    end tell
    if my folderNameMatches(currentFolderName, requestedFolder) then
      tell application "Notes"
        set candidateNotes to every note of theFolder
      end tell
      repeat with noteRef in candidateNotes
        set theNote to contents of noteRef
        set matched to false
        try
          tell application "Notes"
            set candidateId to (id of theNote) as text
            set candidateTitle to (name of theNote) as text
          end tell
          if requestedId is not "" then
            if candidateId is requestedId then set matched to true
          else
            ignoring case
              if candidateTitle is requestedTitle then set matched to true
            end ignoring
          end if
        end try
        if matched then set end of matches to {theNote, currentFolderName}
      end repeat
    end if
  end repeat
  if (count of matches) is 0 then
    if requestedId is not "" then error "No iCloud note was found with id '" & requestedId & "'."
    error "No iCloud note was found with title '" & requestedTitle & "'."
  end if
  if (count of matches) is greater than 1 then error "Multiple iCloud notes match that title; use the note id instead."
  return item 1 of matches
end resolveNote

on noteJson(theNote, folderName, includeBody)
  tell application "Notes"
    set noteId to (id of theNote) as text
    set noteTitle to (name of theNote) as text
    set notePlaintext to (plaintext of theNote) as text
    set createdAt to my isoDate(creation date of theNote)
    set modifiedAt to my isoDate(modification date of theNote)
  end tell
  set notePlaintext to my trimTrailingNewlines(notePlaintext)
  set bodyPart to ""
  if includeBody then set bodyPart to ",\"body\":\"" & my jsonEscape(notePlaintext) & "\""
  return "{\"id\":\"" & my jsonEscape(noteId) & "\",\"title\":\"" & my jsonEscape(noteTitle) & "\",\"folder\":\"" & my jsonEscape(folderName) & "\",\"account\":\"iCloud\",\"created\":\"" & my jsonEscape(createdAt) & "\",\"modified\":\"" & my jsonEscape(modifiedAt) & "\",\"snippet\":\"" & my jsonEscape(my shortText(notePlaintext, 320)) & "\"" & bodyPart & "}"
end noteJson

on jsonArray(valueList)
  if (count of valueList) is 0 then return "[]"
  return "[" & my joinList(valueList, ",") & "]"
end jsonArray

on appendSortedResult(sortedList, newEntry)
  set end of sortedList to newEntry
  set indexNumber to count of sortedList
  repeat while indexNumber is greater than 1
    set currentEntry to item indexNumber of sortedList
    set previousEntry to item (indexNumber - 1) of sortedList
    if (item 2 of currentEntry) is greater than (item 2 of previousEntry) then
      set item indexNumber of sortedList to previousEntry
      set item (indexNumber - 1) of sortedList to currentEntry
      set indexNumber to indexNumber - 1
    else
      exit repeat
    end if
  end repeat
  return sortedList
end appendSortedResult

on searchNotes(folderList, requestedFolder, queryText, maxResults)
  set sortedResults to {}
  repeat with folderRef in folderList
    set theFolder to contents of folderRef
    tell application "Notes"
      set currentFolderName to (name of theFolder) as text
    end tell
    if my folderNameMatches(currentFolderName, requestedFolder) then
      tell application "Notes"
        set candidateNotes to every note of theFolder
      end tell
      repeat with noteRef in candidateNotes
        set theNote to contents of noteRef
        set matched to false
        try
          tell application "Notes"
            set noteTitle to (name of theNote) as text
            set notePlaintext to (plaintext of theNote) as text
          end tell
          set notePlaintext to my trimTrailingNewlines(notePlaintext)
          if queryText is "" then
            set matched to true
          else
            ignoring case
              if noteTitle contains queryText or notePlaintext contains queryText then set matched to true
            end ignoring
          end if
          if matched then
            tell application "Notes"
              set noteModified to modification date of theNote
            end tell
            set noteJsonValue to my noteJson(theNote, currentFolderName, false)
            set sortedResults to my appendSortedResult(sortedResults, {noteJsonValue, noteModified})
          end if
        end try
      end repeat
    end if
  end repeat
  set results to {}
  repeat with resultRef in sortedResults
    set resultEntry to contents of resultRef
    set end of results to item 1 of resultEntry
    if (count of results) is greater than or equal to maxResults then exit repeat
  end repeat
  set resultCount to (count of results)
  return "{\"notes\":" & my jsonArray(results) & ",\"count\":" & (resultCount as text) & "}"
end searchNotes

on readNote(folderList, requestedFolder, requestedId, requestedTitle)
  set match to my resolveNote(folderList, requestedId, requestedTitle, requestedFolder)
  set theNote to item 1 of match
  set folderName to item 2 of match
  return my noteJson(theNote, folderName, true)
end readNote

on writeNote(folderList, requestedFolder, noteTitle, noteBody)
  if noteTitle is "" then error "A note title is required."
  set targetInfo to my findFolder(folderList, requestedFolder)
  set targetFolder to item 1 of targetInfo
  set folderName to item 2 of targetInfo
  set fullText to noteTitle
  if noteBody is not "" then set fullText to noteTitle & return & noteBody
  set noteHtml to my htmlFromPlaintext(fullText)
  tell application "Notes"
    set newNote to make new note at targetFolder with properties {body:noteHtml}
  end tell
  return my noteJson(newNote, folderName, false)
end writeNote

on updateNote(folderList, requestedFolder, requestedId, requestedTitle, noteBody, updateMode)
  if updateMode is not "replace" and updateMode is not "append" then error "Update mode must be replace or append."
  set match to my resolveNote(folderList, requestedId, requestedTitle, requestedFolder)
  set theNote to item 1 of match
  set folderName to item 2 of match
  tell application "Notes"
    set existingTitle to (name of theNote) as text
    set existingPlainText to (plaintext of theNote) as text
  end tell
  set existingPlainText to my trimTrailingNewlines(existingPlainText)
  if updateMode is "replace" then
    set fullText to existingTitle
    if noteBody is not "" then set fullText to existingTitle & return & noteBody
  else
    set fullText to existingPlainText
    if noteBody is not "" then
      if fullText is "" then
        set fullText to noteBody
      else
        set fullText to fullText & return & noteBody
      end if
    end if
  end if
  set noteHtml to my htmlFromPlaintext(fullText)
  tell application "Notes"
    set body of theNote to noteHtml
  end tell
  return my noteJson(theNote, folderName, true)
end updateNote

on deleteNote(folderList, requestedFolder, requestedId, requestedTitle)
  set match to my resolveNote(folderList, requestedId, requestedTitle, requestedFolder)
  set theNote to item 1 of match
  set folderName to item 2 of match
  tell application "Notes"
    set noteId to (id of theNote) as text
    set noteTitle to (name of theNote) as text
    delete theNote
  end tell
  return "{\"deleted\":true,\"id\":\"" & my jsonEscape(noteId) & "\",\"title\":\"" & my jsonEscape(noteTitle) & "\",\"folder\":\"" & my jsonEscape(folderName) & "\",\"account\":\"iCloud\",\"destination\":\"Recently Deleted\"}"
end deleteNote

on run argv
  set action to my argumentAt(argv, 1)
  set requestedFolder to my argumentAt(argv, 2)
  set requestedId to my argumentAt(argv, 3)
  set requestedTitle to my argumentAt(argv, 4)
  set noteBody to my argumentAt(argv, 5)
  set updateMode to my argumentAt(argv, 6)
  set queryText to my argumentAt(argv, 7)
  set maxResults to my positiveInteger(my argumentAt(argv, 8), 10)
  set folderList to my collectFolders()

  if action is "search" then return my searchNotes(folderList, requestedFolder, queryText, maxResults)
  if action is "read" then return my readNote(folderList, requestedFolder, requestedId, requestedTitle)
  if action is "write" then return my writeNote(folderList, requestedFolder, requestedTitle, noteBody)
  if action is "update" then return my updateNote(folderList, requestedFolder, requestedId, requestedTitle, noteBody, updateMode)
  if action is "delete" then return my deleteNote(folderList, requestedFolder, requestedId, requestedTitle)
  error "Unknown Apple Notes action: " & action
end run
`;

type NoteLocator = {
  id?: string;
  title?: string;
  folder?: string;
};

type NoteSearchParams = {
  query?: string;
  folder?: string;
  limit?: number;
};

type NoteWriteParams = {
  title: string;
  body?: string;
  folder?: string;
};

type NoteUpdateParams = NoteLocator & {
  body: string;
  mode: "replace" | "append";
};

type NoteDeleteParams = NoteLocator & {
  confirm?: boolean;
};

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function requireText(value: unknown, name: string): string {
  const text = typeof value === "string" ? value : "";
  if (!text.trim()) throw new Error(`${name} is required`);
  return text;
}

function normalizeTitle(value: unknown): string {
  const title = requireText(value, "title");
  if (/[\r\n]/.test(title)) throw new Error("title must be a single line");
  return title.trim();
}

function normalizeLocator(params: NoteLocator): { id?: string; title?: string; folder: string } {
  const id = cleanText(params.id);
  const title = cleanText(params.title);
  if (!id && !title) throw new Error("Provide either id or title to identify the note");
  return { id: id || undefined, title: id ? undefined : title || undefined, folder: cleanText(params.folder) };
}

function clampLimit(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return DEFAULT_SEARCH_LIMIT;
  return Math.max(1, Math.min(MAX_SEARCH_LIMIT, Math.floor(value)));
}

function formatResult(value: unknown): string {
  const serialized = JSON.stringify(value, null, 2);
  return truncate(serialized ?? String(value), 20_000);
}

function automationError(stderr: string, stdout: string): string {
  const details = (stderr || stdout || "No output from osascript").trim();
  if (/not authorized|not allowed|not permitted|\(-1743\)|\(-10004\)/i.test(details)) {
    return `Apple Notes Automation permission was denied. Allow the Pi/terminal application to control Notes in System Settings → Privacy & Security → Automation.\n${truncate(details, 4_000)}`;
  }
  return `Apple Notes operation failed:\n${truncate(details, 4_000)}`;
}

async function runAppleNotes(
  pi: ExtensionAPI,
  action: string,
  args: { folder?: string; id?: string; title?: string; body?: string; mode?: string; query?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<any> {
  const result = await pi.exec("osascript", [
    "-e",
    APPLE_NOTES_SCRIPT,
    "--",
    action,
    args.folder ?? "",
    args.id ?? "",
    args.title ?? "",
    args.body ?? "",
    args.mode ?? "",
    args.query ?? "",
    String(args.limit ?? DEFAULT_SEARCH_LIMIT),
  ], { signal, timeout: APPLE_SCRIPT_TIMEOUT_MS });

  if (result.code !== 0) throw new Error(automationError(result.stderr, result.stdout));
  const output = result.stdout.trim();
  if (!output) throw new Error("Apple Notes returned no result");
  try {
    return JSON.parse(output);
  } catch (error: any) {
    throw new Error(`Apple Notes returned invalid JSON: ${String(error?.message ?? error)}\n${truncate(output, 4_000)}`);
  }
}

function noteLocatorSchema() {
  return {
    id: Type.Optional(Type.String({ description: "Stable Apple Notes note id; preferred when available." })),
    title: Type.Optional(Type.String({ description: "Exact note title fallback. Fails if multiple notes have the same title." })),
    folder: Type.Optional(Type.String({ description: `Folder name. Defaults to ${DEFAULT_FOLDER} for writes; reads/searches may omit it to scan iCloud folders.` })),
  };
}

function result(value: unknown) {
  return {
    content: [{ type: "text" as const, text: formatResult(value) }],
    details: value,
  };
}

export default function registerAppleNotes(pi: ExtensionAPI) {
  if (process.platform !== "darwin") return;

  pi.registerTool({
    name: "apple_notes_search",
    label: "Apple Notes Search",
    description: "Search iCloud Apple Notes by title and plaintext body. Omit query to list recent notes. Omit folder to search all non-deleted iCloud folders. Load with load_tools({ groups: [\"apple_notes\"] }) before use.",
    parameters: Type.Object({
      query: Type.Optional(Type.String({ description: "Case-insensitive title/body search text. Omit or use an empty string to list notes." })),
      folder: Type.Optional(Type.String({ description: "Optional exact folder name. Omit to search all iCloud folders except Recently Deleted." })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: MAX_SEARCH_LIMIT, description: `Maximum results, default ${DEFAULT_SEARCH_LIMIT}.` })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      const searchParams = params as NoteSearchParams;
      const data = await runAppleNotes(pi, "search", {
        folder: cleanText(searchParams.folder),
        query: searchParams.query ?? "",
        limit: clampLimit(searchParams.limit),
      }, signal);
      return result(data);
    },
  });

  pi.registerTool({
    name: "apple_notes_read",
    label: "Read Apple Note",
    description: "Read one iCloud Apple Note as plaintext by stable note id or exact title. Omit folder to search all non-deleted iCloud folders. Load with load_tools({ groups: [\"apple_notes\"] }) before use.",
    parameters: Type.Object(noteLocatorSchema()),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      const locator = normalizeLocator(params as NoteLocator);
      const data = await runAppleNotes(pi, "read", locator, signal);
      return result(data);
    },
  });

  pi.registerTool({
    name: "apple_notes_write",
    label: "Write Apple Note",
    description: `Create a plaintext iCloud Apple Note. The title is stored as the first line and the body follows it. Defaults to the iCloud → ${DEFAULT_FOLDER} folder. Load with load_tools({ groups: ["apple_notes"] }) before use.`,
    parameters: Type.Object({
      title: Type.String({ minLength: 1, description: "Single-line note title." }),
      body: Type.Optional(Type.String({ description: "Plaintext note body." })),
      folder: Type.Optional(Type.String({ description: `Exact destination folder; defaults to ${DEFAULT_FOLDER}.` })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      const writeParams = params as NoteWriteParams;
      const title = normalizeTitle(writeParams.title);
      const data = await runAppleNotes(pi, "write", {
        folder: cleanText(writeParams.folder) || DEFAULT_FOLDER,
        title,
        body: writeParams.body ?? "",
      }, signal);
      return result(data);
    },
  });

  pi.registerTool({
    name: "apple_notes_update",
    label: "Update Apple Note",
    description: "Update an existing iCloud Apple Note by id or exact title. mode is required: replace preserves the title and replaces its body; append adds text after the current plaintext. Load with load_tools({ groups: [\"apple_notes\"] }) before use.",
    parameters: Type.Object({
      ...noteLocatorSchema(),
      body: Type.String({ description: "Plaintext replacement or text to append." }),
      mode: Type.Union([Type.Literal("replace"), Type.Literal("append")], { description: "Required update behavior." }),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      const updateParams = params as NoteUpdateParams;
      const locator = normalizeLocator(updateParams);
      const data = await runAppleNotes(pi, "update", {
        ...locator,
        body: updateParams.body,
        mode: updateParams.mode,
      }, signal);
      return result(data);
    },
  });

  pi.registerTool({
    name: "apple_notes_delete",
    label: "Delete Apple Note",
    description: "Soft-delete an iCloud Apple Note to Recently Deleted. Requires confirmation; in UI-capable sessions an additional confirmation dialog is shown. Load with load_tools({ groups: [\"apple_notes\"] }) before use.",
    parameters: Type.Object({
      ...noteLocatorSchema(),
      confirm: Type.Optional(Type.Boolean({ description: "Required true in non-UI sessions; UI sessions still show a confirmation dialog." })),
    }),
    executionMode: "sequential",
    async execute(_toolCallId, params, signal, _onUpdate, ctx: ExtensionContext) {
      const deleteParams = params as NoteDeleteParams;
      const locator = normalizeLocator(deleteParams);
      const target = await runAppleNotes(pi, "read", locator, signal);

      if (deleteParams.confirm === false) {
        return result({ deleted: false, cancelled: true, id: target.id, title: target.title, folder: target.folder });
      }
      if (!ctx.hasUI && deleteParams.confirm !== true) {
        throw new Error("Deletion was not performed. Set confirm:true in non-UI sessions.");
      }

      if (ctx.hasUI) {
        const confirmed = await ctx.ui.confirm(
          "Delete Apple Note?",
          `Move “${String(target.title ?? locator.title ?? locator.id)}” to Recently Deleted?\nFolder: ${String(target.folder ?? locator.folder ?? "iCloud")}\nID: ${String(target.id ?? locator.id ?? "unknown")}`,
          { signal },
        );
        if (!confirmed) return result({ deleted: false, cancelled: true, id: target.id, title: target.title, folder: target.folder });
      }

      const data = await runAppleNotes(pi, "delete", locator, signal);
      return result(data);
    },
  });
}
