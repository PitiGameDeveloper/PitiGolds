-- Núcleo de PitiGolds: base de datos, eventos, utilidades y comandos /pg.
local ADDON, ns = ...

ns.VERSION = "0.4.7"
ns.SCHEMA = 1
-- Escaneos que se guardan como máximo mientras el motor no los haya leído.
-- Un escaneo completo de un mega-reino puede ocupar varios MB y WoW carga todo
-- el archivo en cada /reload, así que no conviene acumular muchos.
ns.MAX_PENDING_SCANS = 5

local PREFIX = "|cffe6b422PitiGolds|r: "

function ns.Print(msg)
  DEFAULT_CHAT_FRAME:AddMessage(PREFIX .. tostring(msg))
end

function ns.Log(msg)
  local db = PitiGoldsDB
  if not db or not db.log then return end
  local log = db.log
  log[#log + 1] = date("%Y-%m-%d %H:%M:%S") .. " " .. tostring(msg)
  while #log > 200 do table.remove(log, 1) end
end

-- Los errores se guardan siempre en el log; los tres primeros de cada sesión
-- también salen por el chat para verlos el día que algo cambie en la API.
local shownErrors = 0
function ns.ReportError(context, err)
  ns.Log("ERROR " .. context .. ": " .. tostring(err))
  if shownErrors < 3 then
    shownErrors = shownErrors + 1
    ns.Print("|cffff5555error|r en " .. context .. ": " .. tostring(err))
  end
end

function ns.Trim(s)
  return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- Eventos -------------------------------------------------------------------

local eventFrame = CreateFrame("Frame")
local handlers = {}
ns.missingEvents = {}

-- Registra un manejador. Si el evento no existe en este cliente no rompe nada:
-- queda anotado en el log para revisarlo y devuelve false.
function ns.On(event, fn)
  if not handlers[event] then
    if not pcall(eventFrame.RegisterEvent, eventFrame, event) then
      table.insert(ns.missingEvents, event)
      return false
    end
    handlers[event] = {}
  end
  table.insert(handlers[event], fn)
  return true
end

local BOOT_EVENTS = { ADDON_LOADED = true, PLAYER_LOGIN = true }

eventFrame:SetScript("OnEvent", function(_, event, ...)
  if not ns.ready and not BOOT_EVENTS[event] then return end
  for _, fn in ipairs(handlers[event]) do
    local ok, err = pcall(fn, event, ...)
    if not ok then ns.ReportError(event, err) end
  end
end)

-- Utilidades ----------------------------------------------------------------

local pendingDebounce = {}

-- Ejecuta fn una sola vez tras `delay` segundos aunque se pida muchas veces.
function ns.Debounce(key, delay, fn)
  if pendingDebounce[key] then return end
  pendingDebounce[key] = true
  C_Timer.After(delay, function()
    pendingDebounce[key] = nil
    local ok, err = pcall(fn)
    if not ok then ns.ReportError(key, err) end
  end)
end

-- Recorre 1..total en trozos de `perFrame` por fotograma para no congelar el juego.
function ns.RunChunked(total, perFrame, step, done, context, onError)
  local i = 1
  local function tick()
    local ok, err = pcall(function()
      local last = math.min(i + perFrame - 1, total)
      for idx = i, last do step(idx) end
      i = last + 1
    end)
    if not ok then
      ns.ReportError(context or "proceso", err)
      if onError then onError(err) end
      return
    end
    if i > total then
      if done then
        local okDone, errDone = pcall(done)
        if not okDone then
          ns.ReportError(context or "proceso", errDone)
          if onError then onError(errDone) end
        end
      end
    else
      C_Timer.After(0, tick)
    end
  end
  tick()
end

-- Datos del personaje actual (se crea la primera vez).
function ns.Char()
  local key = ns.charKey
  if not key then return nil end
  local chars = PitiGoldsDB.characters
  local c = chars[key]
  if not c then
    c = {}
    chars[key] = c
  end
  c.inventory = c.inventory or {}
  c.professions = c.professions or {}
  return c
end

function ns.ItemNameByID(itemID)
  if C_Item and C_Item.GetItemNameByID then
    return C_Item.GetItemNameByID(itemID)
  elseif GetItemInfo then
    return (GetItemInfo(itemID))
  end
end

-- Lo que paga un vendedor por una unidad. nil si el objeto aún no está en la caché.
function ns.ItemSellPrice(itemID)
  local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
  if not getInfo then return nil end
  local name, _, _, _, _, _, _, _, _, _, sellPrice = getInfo(itemID)
  if name then return sellPrice or 0 end
end

-- Guarda el nombre y el precio de venta al vendedor de un objeto para el motor. El precio se
-- vuelve a mirar una vez por sesión: Blizzard lo cambia desde el servidor (las varitas pasaron
-- a pagar 1 cobre) y lo guardado en otra sesión puede haberse quedado viejo.
local sellChecked = {}
function ns.NoteItem(itemID, name)
  if not itemID then return end
  local items = PitiGoldsDB.items
  local entry = items[itemID]
  if type(entry) ~= "table" then
    entry = {}
    items[itemID] = entry
  end
  if name and name ~= "" then entry.name = name end
  if not sellChecked[itemID] then
    local sell = ns.ItemSellPrice(itemID)
    if sell then entry.sell, sellChecked[itemID] = sell, true end
  end
end

-- Quita escaneos viejos hasta dejar MAX_PENDING_SCANS. Primero se van los de tus búsquedas
-- (uno por visita a la subasta, con pocos objetos), para no perder un escaneo completo.
local function TrimScans(scans)
  while #scans > ns.MAX_PENDING_SCANS do
    local victim = 1
    for i = 1, #scans - 1 do
      if scans[i].type == "search" then victim = i break end
    end
    table.remove(scans, victim)
  end
end

function ns.AddScan(scan)
  local scans = PitiGoldsDB.scans
  scans[#scans + 1] = scan
  TrimScans(scans)
end

-- Quita los escaneos que el motor ya ha guardado en su base de datos.
function ns.PruneScans()
  local gen = PitiGoldsGenerated
  local upTo = (type(gen) == "table" and tonumber(gen.ingestedUpTo)) or 0
  local kept = {}
  for _, scan in ipairs(PitiGoldsDB.scans) do
    if (scan.time or 0) > upTo then kept[#kept + 1] = scan end
  end
  TrimScans(kept)
  PitiGoldsDB.scans = kept
end

local function InitDB()
  PitiGoldsDB = PitiGoldsDB or {}
  local db = PitiGoldsDB
  db.schema = ns.SCHEMA
  db.addonVersion = ns.VERSION
  db.characters = db.characters or {}
  db.account = db.account or {}
  db.recipes = db.recipes or {}
  db.recipeCategories = db.recipeCategories or {}
  db.items = db.items or {}
  db.vendorItems = db.vendorItems or {}
  db.farmLog = db.farmLog or {}
  db.ledger = db.ledger or {}
  db.scans = db.scans or {}
  db.discovery = db.discovery or {}
  db.log = db.log or {}
  db.ui = db.ui or {}
  local version, build, buildDate, toc = GetBuildInfo()
  db.client = { version = version, build = build, buildDate = buildDate, toc = toc }
  ns.PruneScans()
  for _, event in ipairs(ns.missingEvents) do
    ns.Log("Evento no disponible en este cliente: " .. event)
  end
end

ns.On("ADDON_LOADED", function(_, name)
  if name == ADDON then InitDB() end
end)

ns.On("PLAYER_LOGIN", function()
  local realm = GetNormalizedRealmName() or GetRealmName() or "?"
  ns.charKey = UnitName("player") .. "-" .. realm
  ns.Char()
  ns.ready = true
end)

-- Comandos /pg ----------------------------------------------------------------

local commands, commandOrder = {}, {}

function ns.Command(name, help, fn)
  commands[name] = { help = help, fn = fn }
  commandOrder[#commandOrder + 1] = name
end

SLASH_PITIGOLDS1 = "/pg"
SLASH_PITIGOLDS2 = "/pitigolds"
SlashCmdList.PITIGOLDS = function(msg)
  local cmd, rest = ns.Trim(msg or ""):match("^(%S*)%s*(.-)$")
  local entry = commands[(cmd or ""):lower()]
  if entry then
    local ok, err = pcall(entry.fn, rest)
    if not ok then ns.ReportError("/pg " .. cmd, err) end
    return
  end
  ns.Print("comandos:")
  for _, name in ipairs(commandOrder) do
    ns.Print("  /pg " .. name .. " - " .. commands[name].help)
  end
end

ns.Command("estado", "resumen de lo que hay guardado", function()
  local db = PitiGoldsDB
  local nChars, nRecipes = 0, 0
  for _ in pairs(db.characters) do nChars = nChars + 1 end
  for _ in pairs(db.recipes) do nRecipes = nRecipes + 1 end
  ns.Print(("personaje: %s | personajes: %d | recetas vistas: %d"):format(ns.charKey or "?", nChars, nRecipes))
  local last = db.scans[#db.scans]
  if last then
    ns.Print(("escaneos por leer en el PC: %d | último: %s, %d objetos, hace %d min"):format(
      #db.scans, last.type, last.count or 0, math.floor((time() - last.time) / 60)))
  else
    ns.Print("no hay escaneos por leer en el PC")
  end
  local gen = PitiGoldsGenerated
  if type(gen) == "table" and (gen.generatedAt or 0) > 0 then
    ns.Print(("el motor leyó los datos por última vez hace %d min"):format(math.floor((time() - gen.generatedAt) / 60)))
  else
    ns.Print("el motor todavía no ha leído ningún dato")
  end
end)

ns.Command("log", "muestra las últimas 10 líneas del registro", function()
  local log = PitiGoldsDB.log
  for i = math.max(1, #log - 9), #log do ns.Print(log[i]) end
end)
