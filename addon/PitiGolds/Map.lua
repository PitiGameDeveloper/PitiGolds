-- Dónde están los bichos de tus farmeos activos, pintado en el mapa del mundo (tecla M):
--   - calaveras: donde aparecen según Questie (el motor las pasa con cada farmeo);
--   - rombos: las cosas del mapa del farmeo (almejas, hierbas);
--   - triángulos verdes: donde has matado tú bichos del farmeo. Se apuntan al lootearlos y se
--     guardan por farmeo, así que también sirven en las zonas que Questie no tiene (Clarofluvial).
-- La flecha (Arrow.lua) lleva al punto más cercano de todos ellos.
local ADDON, ns = ...

local M = {}
ns.Map = M

local ICONS = {
  spawn = "Interface\\TargetingFrame\\UI-RaidTargetingIcon_8",
  node = "Interface\\TargetingFrame\\UI-RaidTargetingIcon_3",
  seen = "Interface\\TargetingFrame\\UI-RaidTargetingIcon_4",
}
local MAX_SEEN = 200        -- sitios apuntados por farmeo (se olvidan los más viejos)
local SAME_SPOT = 0.01      -- más cerca que esto (1 % del mapa) es el mismo sitio
local PIN_SIZE = 0.014      -- tamaño de cada marca, en parte del ancho del mapa
local PIN_SIZE_OUTSIDE = 0.008  -- en el mapa del continente

local parsed = {}           -- texto del motor -> lista de puntos
local overlay, pins = nil, {}
local worldCache = {}       -- farmeo -> posiciones en el mundo, para la flecha
local hooked = false

-- «635,620;640,611» (milésimas del mapa) -> { { x = 0.635, y = 0.62 }, ... }
function M.Parse(text)
  if type(text) ~= "string" or text == "" then return {} end
  local cached = parsed[text]
  if cached then return cached end
  local list = {}
  for x, y in text:gmatch("(%d+),(%d+)") do
    list[#list + 1] = { x = tonumber(x) / 1000, y = tonumber(y) / 1000 }
  end
  parsed[text] = list
  return list
end

local function Spots()
  PitiGoldsDB.spots = PitiGoldsDB.spots or {}
  return PitiGoldsDB.spots
end

-- Todos los puntos de un farmeo: { map, x, y, kind = spawn | node | seen }.
function M.Points(f, data)
  local points = {}
  local map = data and data.point and data.point.map
  if map then
    for _, p in ipairs(M.Parse(data.spawns)) do points[#points + 1] = { map = map, x = p.x, y = p.y, kind = "spawn" } end
    for _, p in ipairs(M.Parse(data.nodes)) do points[#points + 1] = { map = map, x = p.x, y = p.y, kind = "node" } end
  end
  for _, s in ipairs(Spots()[f.key] or {}) do
    points[#points + 1] = { map = s.map, x = s.x, y = s.y, kind = "seen" }
  end
  return points
end

-- Cuántos hay de cada clase, para la ventana de farmeos activos.
function M.Counts(f, data)
  local counts = { spawn = 0, node = 0, seen = 0 }
  for _, p in ipairs(M.Points(f, data)) do counts[p.kind] = counts[p.kind] + 1 end
  return counts
end

-- Dónde estás: mapa y coordenadas de 0 a 1, o nil (en mazmorras no hay).
function M.PlayerPosition()
  if not (C_Map and C_Map.GetBestMapForUnit and C_Map.GetPlayerMapPosition) then return nil end
  local map = C_Map.GetBestMapForUnit("player")
  if not map then return nil end
  local pos = C_Map.GetPlayerMapPosition(map, "player")
  if not pos then return nil end
  local x, y = pos:GetXY()
  if not x or not y or (x == 0 and y == 0) then return nil end
  return map, x, y
end

local function Round(v)
  return math.floor(v * 1000 + 0.5) / 1000
end

-- Apunta que has matado aquí un bicho del farmeo. true si es un sitio nuevo.
function M.Record(key)
  local map, x, y = M.PlayerPosition()
  if not map then return false end
  local spots = Spots()
  local list = spots[key] or {}
  spots[key] = list
  for _, s in ipairs(list) do
    if s.map == map and math.abs(s.x - x) < SAME_SPOT and math.abs(s.y - y) < SAME_SPOT then return false end
  end
  list[#list + 1] = { map = map, x = Round(x), y = Round(y) }
  if #list > MAX_SEEN then table.remove(list, 1) end
  worldCache[key] = nil
  M.Refresh()
  return true
end

-- Olvida los sitios apuntados de un farmeo.
function M.Forget(key)
  Spots()[key] = nil
  worldCache[key] = nil
  M.Refresh()
end

-- El punto más cercano a ti de un farmeo (en tu continente), o nil.
function M.Nearest(f, data)
  if not (UnitPosition and C_Map and C_Map.GetWorldPosFromMapPos and CreateVector2D) then return nil end
  local points = M.Points(f, data)
  if #points == 0 then return nil end
  local cache = worldCache[f.key]
  if not cache or cache.n ~= #points or cache.data ~= data then
    cache = { n = #points, data = data, list = {} }
    for _, p in ipairs(points) do
      local continent, pos = C_Map.GetWorldPosFromMapPos(p.map, CreateVector2D(p.x, p.y))
      if pos then
        local north, west = pos:GetXY()
        cache.list[#cache.list + 1] = { north = north, west = west, continent = continent, point = p }
      end
    end
    worldCache[f.key] = cache
  end
  local north, west, _, instance = UnitPosition("player")
  if not north then return nil end
  local best, bestDistance
  for _, w in ipairs(cache.list) do
    if w.continent == instance then
      local d = (w.north - north) ^ 2 + (w.west - west) ^ 2
      if not bestDistance or d < bestDistance then best, bestDistance = w.point, d end
    end
  end
  return best
end

-- Mapa del mundo ---------------------------------------------------------------------------

-- Dónde cae un punto en el mapa que estás viendo (de 0 a 1), o nil si no sale en él.
function M.Project(point, shownMap)
  if point.map == shownMap then return point.x, point.y end
  if not (C_Map and C_Map.GetMapRectOnMap) then return nil end
  local ok, left, right, top, bottom = pcall(C_Map.GetMapRectOnMap, point.map, shownMap)
  if not ok or not left or not right or right == left or bottom == top then return nil end
  local x, y = left + point.x * (right - left), top + point.y * (bottom - top)
  if x < 0 or x > 1 or y < 0 or y > 1 then return nil end
  return x, y
end

local function Canvas()
  local frame = WorldMapFrame
  return frame and frame.ScrollContainer and frame.ScrollContainer.Child
end

-- Vuelve a pintar las marcas (al abrir el mapa, cambiar de mapa o de farmeos).
function M.Refresh()
  local canvas = Canvas()
  if not canvas then return 0 end
  if not overlay then
    overlay = CreateFrame("Frame", nil, canvas)
    overlay:SetAllPoints(canvas)
    if overlay.SetFrameLevel and canvas.GetFrameLevel then overlay:SetFrameLevel(canvas:GetFrameLevel() + 500) end
  end
  local n = 0
  local shown = WorldMapFrame:IsShown() and WorldMapFrame.GetMapID and WorldMapFrame:GetMapID()
  if shown then
    local width, height = canvas:GetWidth(), canvas:GetHeight()
    for _, f in ipairs(ns.Tracker.List()) do
      if f.kind == "farm" then
        for _, p in ipairs(M.Points(f, ns.Tracker.Data(f))) do
          local x, y = M.Project(p, shown)
          if x then
            n = n + 1
            local pin = pins[n]
            if not pin then
              pin = overlay:CreateTexture(nil, "OVERLAY")
              pins[n] = pin
            end
            local size = math.max(6, width * (p.map == shown and PIN_SIZE or PIN_SIZE_OUTSIDE))
            pin:SetTexture(ICONS[p.kind])
            pin:SetSize(size, size)
            pin:ClearAllPoints()
            pin:SetPoint("CENTER", overlay, "TOPLEFT", x * width, -y * height)
            pin:Show()
          end
        end
      end
    end
  end
  for i = n + 1, #pins do pins[i]:Hide() end
  return n
end

local function Hook()
  if hooked or not Canvas() then return end
  hooked = true
  if WorldMapFrame.OnMapChanged then hooksecurefunc(WorldMapFrame, "OnMapChanged", M.Refresh) end
  WorldMapFrame:HookScript("OnShow", M.Refresh)
  Canvas():HookScript("OnSizeChanged", M.Refresh)
end

ns.On("PLAYER_LOGIN", Hook)
ns.On("ADDON_LOADED", function(_, name)
  if name == "Blizzard_WorldMap" then Hook() end
end)

ns.Command("olvidar", "olvida los sitios donde has matado bichos de un farmeo activo: /pg olvidar <farmeo>",
  function(arg)
    local wanted = ns.Trim(arg or ""):lower()
    for _, f in ipairs(ns.Tracker.List()) do
      if f.kind == "farm" and (wanted == "" or f.key:lower() == wanted or (f.name or ""):lower() == wanted) then
        M.Forget(f.key)
        ns.Print(("olvidados los sitios apuntados de «%s»."):format(f.name or f.key))
        return
      end
    end
    ns.Print("no tienes activo ese farmeo.")
  end)
