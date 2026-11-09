-- Frosted Glass Blur Rules for Waybar and Stark Rice Desktop Cards
hl.layer_rule({ match = { namespace = "^(topbar|leftdock|stark-sysmon|stark-music|stark-quote)$" }, blur = true })
hl.layer_rule({ match = { namespace = "^(topbar|leftdock|stark-sysmon|stark-music|stark-quote)$" }, ignore_alpha = 0.08 })

-- Zenify Music Panel Floating Window Rules
hl.window_rule({ match = { class = "^(zenify|stark-spotify)$" }, float = true })
hl.window_rule({ match = { class = "^(zenify|stark-spotify)$" }, center = true })
hl.window_rule({ match = { class = "^(zenify|stark-spotify)$" }, size = { 860, 520 } })
hl.window_rule({ match = { title = "^(Zenify)$" }, float = true })
hl.window_rule({ match = { title = "^(Zenify)$" }, center = true })
hl.window_rule({ match = { title = "^(Zenify)$" }, size = { 860, 520 } })
