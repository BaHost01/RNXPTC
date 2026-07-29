"""
rbxinit – Luau init payload compiler.

Injects into the Url ModuleScript (Modules/Common/Url), which is always loaded.
The script:
  1. Uses task.spawn to run the injection logic asynchronously (compatible
     with the local third-party luau compiler, which does not support
     coroutine.wrap(...)() as a statement).
  2. Creates a Syntax folder in CoreGui (injection signal for Python host).
  3. Sets up getgenv() with UNC functions backed by the HTTP bridge.
  4. Polls /send?c=gs every 0.5s for scripts to execute.
  5. Returns the Url patch table so the module keeps working.
"""

from luau import compile_roblox


def get() -> bytes:
    """Compile the init payload into Roblox-ready bytecode."""

    source = (
        "--!nonstrict\n"

        # ── Spawn the init coroutine so we don't block the require chain ──
        "task.spawn(function()\n"

        "local BRIDGE    = \"http://127.0.0.1:19283\"\n"
        "local EXEC_NAME = \"Syntax\"\n"
        "local HS = game:GetService(\"HttpService\")\n"
        "local CG = game:GetService(\"CoreGui\")\n"

        # Signal: create Syntax folder
        "local existing = CG:FindFirstChild(EXEC_NAME)\n"
        "if existing then existing:Destroy() end\n"
        "local container = Instance.new(\"Folder\")\n"
        "container.Name   = EXEC_NAME\n"
        "container.Parent = CG\n"

        # Helper: POST JSON to bridge
        "local function bridge_post(cmd, extra)\n"
        "    local body = { c = cmd }\n"
        "    if extra then\n"
        "        for k, v in pairs(extra) do body[k] = v end\n"
        "    end\n"
        "    local ok, res = pcall(function()\n"
        "        return HS:RequestInternal({\n"
        "            Url     = BRIDGE .. \"/send\",\n"
        "            Method  = \"POST\",\n"
        "            Headers = { [\"Content-Type\"] = \"application/json\" },\n"
        "            Body    = HS:JSONEncode(body),\n"
        "        })\n"
        "    end)\n"
        "    if ok and res and res.Success then\n"
        "        return res.Body, res.StatusCode\n"
        "    end\n"
        "    return nil, 0\n"
        "end\n"

        # Helper: GET from bridge
        "local function bridge_get(path)\n"
        "    local ok, res = pcall(function()\n"
        "        return HS:RequestInternal({\n"
        "            Url    = BRIDGE .. path,\n"
        "            Method = \"GET\",\n"
        "        })\n"
        "    end)\n"
        "    if ok and res and res.Success then\n"
        "        return res.Body, res.StatusCode\n"
        "    end\n"
        "    return nil, 0\n"
        "end\n"

        # Global environment
        "local genv = {}\n"
        "genv.getgenv = function() return genv end\n"

        "genv.writefile = function(path, content)\n"
        "    pcall(function()\n"
        "        HS:RequestInternal({\n"
        "            Url     = BRIDGE .. \"/writefile?p=\" .. tostring(path),\n"
        "            Method  = \"POST\",\n"
        "            Headers = { [\"Content-Type\"] = \"application/octet-stream\" },\n"
        "            Body    = tostring(content),\n"
        "        })\n"
        "    end)\n"
        "end\n"

        "genv.readfile = function(path)\n"
        "    local body = bridge_post(\"rf\", { p = path })\n"
        "    return body or \"\"\n"
        "end\n"

        "genv.listfiles = function(path)\n"
        "    local body = bridge_post(\"lf\", { p = path or \"\" })\n"
        "    if body then\n"
        "        local ok, t = pcall(HS.JSONDecode, HS, body)\n"
        "        if ok and t then return t end\n"
        "    end\n"
        "    return {}\n"
        "end\n"

        "genv.delfile = function(path)\n"
        "    bridge_post(\"df\", { p = path })\n"
        "end\n"

        "genv.isfile = function(path)\n"
        "    local body = bridge_post(\"fe\", { p = path })\n"
        "    if body then\n"
        "        local ok, v = pcall(HS.JSONDecode, HS, body)\n"
        "        if ok then return v == true end\n"
        "    end\n"
        "    return false\n"
        "end\n"

        "genv.appendfile = function(path, content)\n"
        "    bridge_post(\"af\", { p = path, v = tostring(content) })\n"
        "end\n"

        "genv.print = print\n"
        "genv.warn  = warn\n"
        "genv.error = error\n"

        # Expose getgenv globally
        "_G.getgenv = genv.getgenv\n"

        # Notification
        "task.spawn(function()\n"
        "    pcall(function()\n"
        "        game:GetService(\"StarterGui\"):SetCore(\"SendNotification\", {\n"
        "            Title    = \"Syntax Executor v1\",\n"
        "            Text     = \"Injected successfully!\",\n"
        "            Duration = 5,\n"
        "        })\n"
        "    end)\n"
        "end)\n"

        # Execution loop
        "task.spawn(function()\n"
        "    print(\"[SYNTAX] Execution loop started\")\n"
        "    while true do\n"
        "        local body, status = bridge_get(\"/send?c=gs\")\n"
        "        if body and status == 200 and #body > 0 then\n"
        "            local fn, err = loadstring(body)\n"
        "            if fn then\n"
        "                setfenv(fn, genv)\n"
        "                task.spawn(function()\n"
        "                    local ok2, err2 = pcall(fn)\n"
        "                    if not ok2 then\n"
        "                        warn(\"[SYNTAX] Script error: \" .. tostring(err2))\n"
        "                    end\n"
        "                end)\n"
        "            else\n"
        "                warn(\"[SYNTAX] Compile error: \" .. tostring(err))\n"
        "            end\n"
        "        end\n"
        "        task.wait(0.5)\n"
        "    end\n"
        "end)\n"

        "print(\"[SYNTAX] Init complete\")\n"

        # End of task.spawn
        "end)\n"

        # ── Url patch: return a valid URL table so the module keeps working ──
        "\n"
        "local urlTable = {}\n"
        "local cp = game:GetService(\"ContentProvider\")\n"
        "\n"
        "local function stripToDomain(baseUrl)\n"
        "    local _, dotPos = baseUrl:find(\"\\.\")\n"
        "    local domain = baseUrl:sub(dotPos + 1)\n"
        "    if domain:sub(-1) ~= \"/\" then\n"
        "        domain = domain .. \"/\"\n"
        "    end\n"
        "    return domain\n"
        "end\n"
        "\n"
        "local domain = stripToDomain(cp.BaseUrl)\n"
        "\n"
        "local urls = {\n"
        "    GAME_URL                      = string.format(\"https://games.%s\", domain),\n"
        "    RCS_URL                       = string.format(\"https://apis.rcs.%s\", domain),\n"
        "    APIS_URL                      = string.format(\"https://apis.%s\", domain),\n"
        "    ACCOUNT_SETTINGS_URL          = string.format(\"https://accountsettings.%s\", domain),\n"
        "    GAME_INTERNATIONALIZATION_URL = string.format(\"https://gameinternationalization.%s\", domain),\n"
        "    LOCALE_URL                    = string.format(\"https://locale.%s\", domain),\n"
        "    ROLES_URL                     = string.format(\"https://users.%s\", domain),\n"
        "}\n"
        "\n"
        "setmetatable(urlTable, {\n"
        "    __newindex = function(t, k, v) end,\n"
        "    __index    = function(t, k) return urls[k] end,\n"
        "})\n"
        "\n"
        "return urlTable\n"
    )

    bytecode = compile_roblox(source, pack=True)
    return bytecode
