import AppIntents

/// The only host Siri surface on iPhone and Watch. Siri invokes the shortcut
/// with the bare phrase, then resolves the required free-form String through
/// its supported spoken value-prompt flow.
struct JARVISAppShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: SendPromptToJARVISIntent(),
            phrases: ["Hey \(.applicationName)"],
            shortTitle: "Talk to JARVIS",
            systemImageName: "waveform"
        )
    }
}
