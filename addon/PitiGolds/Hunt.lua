-- Caza: los bichos de tus farmeos activos.
--   - Macro «PG Objetivo» (uno solo, general): el addon le reescribe los /target cada vez que
--     activas o acabas un farmeo, o aprende un bicho nuevo. /target elige el bicho más cercano
--     cuyo nombre empiece por lo que le das, así que con «Arpía» vale para todas las arpías; con
--     nombres distintos prueba uno detrás de otro, primero los que tienes a la vista. Fuera de
--     combate: en combate WoW no deja cambiar macros, así que espera a que acabe.
--   - Marcas: una calavera sobre la placa de cada bicho de tus farmeos (hacen falta las placas
--     de enemigos, tecla V). Es dibujo del addon: las marcas de banda de verdad no se pueden
--     poner desde un addon.
--   - Aprende: al lootear un objeto de un farmeo en marcha, apunta el bicho que lo soltó; y
--     «Añadir objetivo» apunta el que tengas seleccionado.
local ADDON, ns = ...

local H = {}
ns.Hunt = H

local MACRO_NAME = "PG Objetivo"
local MACRO_ICON = "Ability_Hunter_SniperShot"
local MAX_BODY = 255
local MAX_LEARNED = 6            -- bichos apuntados por farmeo al lootear
local SKULL = "Interface\\TargetingFrame\\UI-RaidTargetingIcon_8"

local names, learnedIDs = {}, {}    -- lo que se busca ahora (se rehace en H.Update)
local visible = {}                   -- nombre buscado -> placas a la vista
local marks = {}                     -- placa -> calavera
local macrosReady, pendingMacro, lastBody, hinted = false, false, nil, false

local function NpcID(guid)
  if type(guid) ~= "string" then return nil end
  local kind, id = guid:match("^(%a+)%-%d+%-%d+%-%d+%-%d+%-(%d+)")
  if kind == "Creature" or kind == "Vehicle" then return tonumber(id) end
end
H.NpcID = NpcID

local function StartsWith(name, prefix)
  return name:sub(1, #prefix):lower() == prefix:lower()
end

-- Los bichos de un farmeo: los del catálogo y los apuntados, sin repetir.
function H.Names(f)
  local list, seen = {}, {}
  local function add(name)
    if type(name) == "string" and name ~= "" and not seen[name:lower()] then
      list[#list + 1], seen[name:lower()] = name, true
    end
  end
  local data = ns.Tracker.Data(f)
  for _, name in ipairs(data and data.mobs or {}) do add(name) end
  local ids = {}
  for id in pairs(f.mobs or {}) do ids[#ids + 1] = id end
  table.sort(ids)
  for _, id in ipairs(ids) do add(f.mobs[id]) end
  return list
end

-- Todos los nombres que busca el macro: los que empiezan por otro de la lista sobran (/target
-- ya los encuentra con el más corto).
function H.AllNames()
  local all, seen = {}, {}
  for _, f in ipairs(ns.Tracker.List()) do
    if f.kind == "farm" then
      for _, name in ipairs(H.Names(f)) do
        if not seen[name:lower()] then all[#all + 1], seen[name:lower()] = name, true end
      end
    end
  end
  local kept = {}
  for i, name in ipairs(all) do
    local covered = false
    for j, other in ipairs(all) do
      if i ~= j and #other < #name and StartsWith(name, other) then covered = true end
    end
    if not covered then kept[#kept + 1] = name end
  end
  return kept
end

function H.IsTargetOf(f)
  local id = NpcID(UnitGUID("target"))
  return id ~= nil and f.mobs ~= nil and f.mobs[id] ~= nil
end

-- Macro --------------------------------------------------------------------------------------

function H.MacroBody(list)
  if #list == 0 then return "/pg objetivo" end
  -- Primero los que hay a la vista; si no, en el orden de tus farmeos.
  local order = {}
  for i, name in ipairs(list) do order[i] = { name = name, i = i, seen = (visible[name] or 0) > 0 } end
  table.sort(order, function(a, b)
    if a.seen ~= b.seen then return a.seen end
    return a.i < b.i
  end)
  local tail = "/cleartarget [dead]"
  local lines = { "/cleartarget", "/tar " .. order[1].name }
  local length = #lines[1] + 1 + #lines[2] + 1 + #tail
  for i = 2, #order do
    local line = "/tar [noexists] " .. order[i].name
    if length + 1 + #line > MAX_BODY then break end
    lines[#lines + 1] = line
    length = length + 1 + #line
  end
  lines[#lines + 1] = tail
  return table.concat(lines, "\n")
end

-- create: si no existe, se crea (solo cuando lo pides tú, no al entrar en el juego).
function H.UpdateMacro(create)
  if not GetMacroIndexByName or not macrosReady then return end
  if InCombatLockdown() then
    pendingMacro = true
    return
  end
  pendingMacro = false
  local body = H.MacroBody(names)
  local index = GetMacroIndexByName(MACRO_NAME)
  if not index or index == 0 then
    if not create or #names == 0 then return end
    local ok, err = pcall(CreateMacro, MACRO_NAME, MACRO_ICON, body, nil)
    if ok then
      lastBody = body
      ns.Print("he creado el macro «" .. MACRO_NAME .. "» (Esc > Macros, pestaña general). Ponlo en tu barra:"
        .. " selecciona el bicho más cercano de tus farmeos activos y se cambia solo al activar o acabar uno.")
    else
      ns.Print("no he podido crear el macro «" .. MACRO_NAME .. "» (¿tienes llenas las macros generales?): "
        .. tostring(err))
    end
    return
  end
  if body == lastBody then return end
  local ok, err = pcall(EditMacro, index, MACRO_NAME, MACRO_ICON, body)
  if ok then lastBody = body else ns.ReportError("macro", err) end
end

-- Placas ---------------------------------------------------------------------------------------

local function Mark(plate, on)
  local mark = marks[plate]
  if not on then
    if mark then mark:Hide() end
    return
  end
  if not mark then
    mark = CreateFrame("Frame", nil, plate)
    mark:SetSize(24, 24)
    mark:SetPoint("BOTTOM", plate, "TOP", 0, 0)
    mark.icon = mark:CreateTexture(nil, "OVERLAY")
    mark.icon:SetAllPoints()
    mark.icon:SetTexture(SKULL)
    local pulse = mark.CreateAnimationGroup and mark:CreateAnimationGroup()
    if pulse then
      pulse:SetLooping("BOUNCE")
      local fade = pulse:CreateAnimation("Alpha")
      fade:SetFromAlpha(1)
      fade:SetToAlpha(0.4)
      fade:SetDuration(0.6)
      pulse:Play()
    end
    marks[plate] = mark
  end
  mark:Show()
end

-- El nombre buscado al que corresponde una unidad, o nil.
function H.Matches(unit)
  local ok, result = pcall(function()
    if UnitIsDead and UnitIsDead(unit) then return nil end
    local id = NpcID(UnitGUID(unit))
    if id and learnedIDs[id] then return learnedIDs[id] end
    local name = UnitName(unit)
    if type(name) ~= "string" then return nil end
    for _, wanted in ipairs(names) do
      if StartsWith(name, wanted) then return wanted end
    end
  end)
  return ok and result or nil
end

local plateMatch = {}   -- unidad -> nombre buscado

local function PlateFor(unit)
  local plate = C_NamePlate and C_NamePlate.GetNamePlateForUnit and C_NamePlate.GetNamePlateForUnit(unit)
  if plate and plate.IsForbidden and plate:IsForbidden() then return nil end
  return plate
end

local function Unwatch(unit)
  local was = plateMatch[unit]
  if was then visible[was] = math.max(0, (visible[was] or 1) - 1) end
  plateMatch[unit] = nil
end

local function Watch(unit)
  Unwatch(unit)
  local plate = PlateFor(unit)
  if not plate then return end
  local match = H.Matches(unit)
  Mark(plate, match ~= nil)
  if match then
    plateMatch[unit] = match
    visible[match] = (visible[match] or 0) + 1
  end
end

local function RefreshPlates()
  if not C_NamePlate or not C_NamePlate.GetNamePlates then return end
  for unit in pairs(plateMatch) do Unwatch(unit) end
  for plate in pairs(marks) do Mark(plate, false) end
  for _, plate in ipairs(C_NamePlate.GetNamePlates() or {}) do
    local unit = plate.namePlateUnitToken or (plate.UnitFrame and plate.UnitFrame.unit)
    if unit then Watch(unit) end
  end
end

-- Lo que hace falta cuando cambian tus farmeos activos o sus bichos.
function H.Update(create)
  names = H.AllNames()
  learnedIDs = {}
  for _, f in ipairs(ns.Tracker.List()) do
    if f.kind == "farm" then
      for id, name in pairs(f.mobs or {}) do learnedIDs[id] = name end
    end
  end
  RefreshPlates()
  H.UpdateMacro(create)
end

-- Al activar un farmeo desde la ventana de métodos.
function H.Activated()
  H.Update(true)
  if #names > 0 and not hinted and GetCVar and GetCVar("nameplateShowEnemies") == "0" then
    hinted = true
    ns.Print("activa las placas de los enemigos (tecla V) para ver la calavera sobre los bichos de tus farmeos.")
  end
end

-- Aprender bichos --------------------------------------------------------------------------------

local function Covered(f, name)
  local data = ns.Tracker.Data(f)
  for _, seed in ipairs(data and data.mobs or {}) do
    if StartsWith(name, seed) then return true end
  end
  return false
end

function H.Learn(f, id, name)
  if not f.mobs then f.mobs = {} end
  if f.mobs[id] or Covered(f, name) then return false end
  local n = 0
  for _ in pairs(f.mobs) do n = n + 1 end
  if n >= MAX_LEARNED then return false end
  f.mobs[id] = name
  ns.Print(("apunto «%s» como bicho de «%s»."):format(name, f.name or f.key))
  return true
end

function H.ToggleTarget(f)
  local id = NpcID(UnitGUID("target"))
  if not id then
    ns.Print("selecciona primero un bicho y vuelve a pulsar.")
    return
  end
  f.mobs = f.mobs or {}
  if f.mobs[id] then
    ns.Print(("quito «%s» de «%s»."):format(f.mobs[id], f.name or f.key))
    f.mobs[id] = nil
  else
    f.mobs[id] = UnitName("target")
    ns.Print(("apunto «%s» como bicho de «%s»."):format(f.mobs[id], f.name or f.key))
  end
  H.Update(true)
  ns.Tracker.Refresh()
end

local function NameOf(guid)
  for _, unit in ipairs({ "target", "mouseover" }) do
    if UnitGUID(unit) == guid then return UnitName(unit) end
  end
end

-- Al abrir un botín: el bicho que soltó un objeto de un farmeo en marcha (con sitio fijo: los
-- de «cualquier zona» apuntarían todo lo que matas) es de ese farmeo.
local function OnLoot()
  if not GetNumLootItems or not GetLootSourceInfo then return end
  local running = {}
  for _, f in ipairs(ns.Tracker.List()) do
    local data = f.kind == "farm" and f.started and ns.Tracker.Data(f)
    if data and data.point and data.items and #data.items > 0 then running[#running + 1] = { f = f, data = data } end
  end
  if #running == 0 then return end
  local learned = false
  for slot = 1, GetNumLootItems() do
    local link = GetLootSlotLink(slot)
    local itemID = link and tonumber(link:match("item:(%d+)"))
    if itemID then
      local sources = { GetLootSourceInfo(slot) }
      for i = 1, #sources, 2 do
        local guid = sources[i]
        local id = NpcID(guid)
        local name = id and NameOf(guid)
        if name then
          for _, r in ipairs(running) do
            if ns.Tracker.IsFarmItem(r.data, itemID) and H.Learn(r.f, id, name) then learned = true end
          end
        end
      end
    end
  end
  if learned then
    H.Update(true)
    ns.Tracker.Refresh()
  end
end

ns.On("LOOT_OPENED", function()
  local ok, err = pcall(OnLoot)
  if not ok then ns.ReportError("botín", err) end
end)

ns.On("NAME_PLATE_UNIT_ADDED", function(_, unit)
  Watch(unit)
  if plateMatch[unit] and not InCombatLockdown() then ns.Debounce("huntMacro", 1, H.UpdateMacro) end
end)
ns.On("NAME_PLATE_UNIT_REMOVED", function(_, unit)
  Unwatch(unit)
  local plate = PlateFor(unit)
  if plate then Mark(plate, false) end
end)

ns.On("PLAYER_REGEN_ENABLED", function()
  if pendingMacro then H.UpdateMacro() end
end)

-- Las macros llegan del servidor después de entrar: antes, el macro parecería no existir.
local function MacrosLoaded()
  if macrosReady then return end
  macrosReady = true
  H.Update()
end
ns.On("UPDATE_MACROS", MacrosLoaded)
ns.On("PLAYER_LOGIN", function()
  C_Timer.After(10, MacrosLoaded)
end)

ns.Command("objetivo", "los bichos que busca el macro «PG Objetivo» (y lo crea si no está)", function()
  H.Update(true)
  if #names == 0 then
    ns.Print("ningún farmeo activo tiene bichos todavía: se apuntan al lootear sus objetos, o con «Añadir"
      .. " objetivo» en la ventana de farmeos activos.")
  else
    ns.Print("el macro «" .. MACRO_NAME .. "» busca: " .. table.concat(names, ", "))
  end
end)
