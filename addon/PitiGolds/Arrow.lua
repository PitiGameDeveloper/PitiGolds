-- Flecha hacia el sitio de tu farmeo activo (el primero de la lista que esté en marcha, o si
-- no el primero, que tenga sitio en el catálogo), como la de TomTom: gira según hacia dónde
-- miras y dice a cuántos metros está. Si el catálogo solo da la zona, lleva hasta ella y avisa
-- cuando estás dentro. Además pone el punto en el mapa del juego si el cliente lo permite.
-- Se mueve arrastrándola; clic derecho la esconde (/pg flecha la vuelve a enseñar).
local ADDON, ns = ...

local A = {}
ns.Arrow = A

local ARRIVED = 40               -- metros: has llegado
local UPDATE_EVERY = 0.1
local TEXTURE = "Interface\\Minimap\\MinimapArrow"

local frame, arrow, label
local destKey

local function MapName(map)
  local info = C_Map and C_Map.GetMapInfo and C_Map.GetMapInfo(map)
  return info and info.name or ("mapa " .. tostring(map))
end

-- El farmeo al que lleva la flecha y su fila del motor.
function A.Destination()
  local firstF, firstData
  for _, f in ipairs(ns.Tracker.List()) do
    local data = f.kind == "farm" and ns.Tracker.Data(f)
    if data and data.point then
      if f.started then return f, data end
      if not firstF then firstF, firstData = f, data end
    end
  end
  return firstF, firstData
end

-- Hacia dónde y a cuánto: { text, angle (radianes, 0 = de frente, positivo a la izquierda),
-- distance, arrived }.
function A.Compute(point)
  local zone = MapName(point.map)
  if not (UnitPosition and C_Map and C_Map.GetWorldPosFromMapPos and CreateVector2D) then return { text = zone } end
  local here = C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
  if not point.x and here == point.map then return { text = "Estás en " .. zone, arrived = true } end
  -- UnitPosition da primero la coordenada norte y luego la oeste, como GetWorldPosFromMapPos.
  local north, west, _, instance = UnitPosition("player")
  if not north then return { text = zone .. " (aquí no sé dónde estás)" } end
  local continent, pos = C_Map.GetWorldPosFromMapPos(point.map, CreateVector2D(point.x or 0.5, point.y or 0.5))
  if not pos then return { text = zone } end
  if continent ~= instance then return { text = zone .. " (en el otro continente)" } end
  local tNorth, tWest = pos:GetXY()
  local dNorth, dWest = tNorth - north, tWest - west
  local distance = math.sqrt(dNorth * dNorth + dWest * dWest)
  if point.x and distance <= ARRIVED then return { text = "Has llegado", arrived = true, distance = distance } end
  local facing = GetPlayerFacing and GetPlayerFacing()
  -- Ángulo contado desde el norte hacia el oeste, igual que GetPlayerFacing.
  local angle = facing and (math.atan2(dWest, dNorth) - facing) or nil
  local text = ("%s%d m"):format(point.x and "" or "~", math.floor(distance + 0.5))
  if not point.x then text = zone .. " · " .. text end
  return { text = text, angle = angle, distance = distance }
end

local function Settings()
  PitiGoldsDB.ui.arrow = PitiGoldsDB.ui.arrow or {}
  return PitiGoldsDB.ui.arrow
end

local function OnTick()
  local f, data = A.Destination()
  if not f then return end
  local state = A.Compute(data.point)
  if state.angle and arrow.SetRotation then
    arrow:SetRotation(state.angle)
    arrow:Show()
  else
    arrow:Hide()
  end
  label:SetText((f.name or f.key) .. "\n" .. state.text)
end

local function CreateArrow()
  local s = Settings()
  frame = CreateFrame("Button", "PitiGoldsArrow", UIParent)
  frame:SetSize(56, 56)
  if s.point then
    frame:SetPoint(s.point[1], UIParent, s.point[2], s.point[3], s.point[4])
  else
    frame:SetPoint("TOP", UIParent, "TOP", 0, -120)
  end
  frame:SetMovable(true)
  frame:SetClampedToScreen(true)
  frame:EnableMouse(true)
  frame:RegisterForDrag("LeftButton")
  frame:RegisterForClicks("RightButtonUp")
  frame:SetScript("OnDragStart", frame.StartMoving)
  frame:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    local point, _, relativePoint, x, y = self:GetPoint()
    Settings().point = { point, relativePoint, x, y }
  end)
  frame:SetScript("OnClick", function()
    A.Hide()
    ns.Print("flecha escondida: /pg flecha la vuelve a enseñar.")
  end)
  arrow = frame:CreateTexture(nil, "OVERLAY")
  arrow:SetTexture(TEXTURE)
  arrow:SetSize(48, 48)
  arrow:SetPoint("CENTER")
  label = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  label:SetPoint("TOP", frame, "BOTTOM", 0, -2)
  local since = 0
  frame:SetScript("OnUpdate", function(_, elapsed)
    since = since + elapsed
    if since >= UPDATE_EVERY then
      since = 0
      OnTick()
    end
  end)
end

-- El punto en el mapa del juego (y su indicador en pantalla), si el cliente lo tiene.
local function SetWaypoint(point)
  if not point.x or not (C_Map and C_Map.SetUserWaypoint and UiMapPoint and UiMapPoint.CreateFromCoordinates) then
    return
  end
  pcall(function()
    if C_Map.CanSetUserWaypointOnMap and not C_Map.CanSetUserWaypointOnMap(point.map) then return end
    C_Map.SetUserWaypoint(UiMapPoint.CreateFromCoordinates(point.map, point.x, point.y))
    if C_SuperTrack and C_SuperTrack.SetSuperTrackedUserWaypoint then C_SuperTrack.SetSuperTrackedUserWaypoint(true) end
  end)
end

-- Cuando cambian tus farmeos activos.
function A.Update()
  local f, data = A.Destination()
  if not f then
    destKey = nil
    if frame then frame:Hide() end
    return
  end
  if f.key ~= destKey then
    destKey = f.key
    SetWaypoint(data.point)
  end
  if Settings().hidden then return end
  if not frame then CreateArrow() end
  frame:Show()
  OnTick()
end

function A.Hide()
  Settings().hidden = true
  if frame then frame:Hide() end
end

function A.Text()
  return label and label:GetText() or ""
end

ns.On("PLAYER_LOGIN", function()
  C_Timer.After(2, A.Update)
end)

ns.Command("flecha", "enseña o esconde la flecha hacia tu farmeo activo", function()
  if Settings().hidden or not (frame and frame:IsShown()) then
    Settings().hidden = nil
    A.Update()
    if not A.Destination() then ns.Print("ningún farmeo activo tiene sitio en el catálogo.") end
  else
    A.Hide()
  end
end)
