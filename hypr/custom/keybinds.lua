hl.bind("CTRL+SUPER+ALT+Slash", hl.dsp.exec_cmd("xdg-open ~/.config/hypr/custom/keybinds.lua"), {description = "Edit user keybinds"} )

-- Move active window to workspace and follow
for i = 1, 10 do
    hl.bind("SUPER + SHIFT + " .. (i % 10), function()
        hl.dispatch(hl.dsp.global("quickshell:searchToggleReleaseInterrupt"))
        hl.dispatch(hl.dsp.window.move({ workspace = workspace_in_group(i), follow = true }))
    end, { description = "Window: Move to workspace and follow " .. i })
end

-- Raw keycodes for different keyboard layouts (1-0 row: keycodes 10-19)
for i = 1, 10 do
    local numberkey = { 10, 11, 12, 13, 14, 15, 16, 17, 18, 19 }
    hl.bind("SUPER + SHIFT + code:" .. numberkey[i], function()
        hl.dispatch(hl.dsp.global("quickshell:searchToggleReleaseInterrupt"))
        hl.dispatch(hl.dsp.window.move({ workspace = workspace_in_group(i), follow = true }))
    end)
end

-- Keypad numbers (KP_1 to KP_0)
for i = 1, 10 do
    local numpadkey = { 87, 88, 89, 83, 84, 85, 79, 80, 81, 90 }
    hl.bind("SUPER + SHIFT + code:" .. numpadkey[i], function()
        hl.dispatch(hl.dsp.global("quickshell:searchToggleReleaseInterrupt"))
        hl.dispatch(hl.dsp.window.move({ workspace = workspace_in_group(i), follow = true }))
    end)
end


-- Reload Stark Rice UI (Bars & Widgets)
hl.bind("CTRL + SUPER + B", hl.dsp.exec_cmd("$HOME/.config/stark-rice/launch.sh"), { description = "Reload Stark UI" })

-- Win + P -> Custom Integrated Spotify Player
hl.bind("SUPER + P", hl.dsp.exec_cmd("python3 $HOME/.config/stark-rice/stark_spotify.py --toggle"), { description = "Stark Spotify: Toggle Player" })
