-- Interfaz mínima: un panel movible con lo que llevas ganado en la sesión y los botones
-- Mejor farmeo (ventana de métodos), Sesión (lista de lo farmeado) y Farmeos activos, y dos botones de
-- escaneo encima de la ventana de la subasta. Se pone al día en cuanto entra algo en las
-- bolsas o cambia tu oro. No hace falta exportar: WoW guarda los datos al cambiar de
-- personaje, al salir o con /reload.
local ADDON, ns = ...

local CLOCK_SECONDS = 60   -- sin botín, solo cambian los minutos y el oro por hora
local LINE_HEIGHT = 12

local panel, statusText
local ahBar, ahStatus

local function Ago(t)
  local minutes = math.floor((time() - t) / 60)
  if minutes < 1 then return "ahora" end
  if minutes < 60 then return ("hace %d min"):format(minutes) end
  return ("hace %d h"):format(math.floor(minutes / 60))
end

local function Silver(copper)
  return ns.Money(math.floor(copper / 100) * 100)
end

function ns.RefreshUI()
  local lines = {}
  local s = ns.Session and ns.Session.Summary()
  if s then
    local total = s.total > 0 and ns.Money(s.total) or "nada todavía"
    lines[#lines + 1] = ("Sesión (%s): %s"):format(ns.Session.Duration(s.elapsed), total)
    if s.total > 0 then lines[#lines + 1] = "Por hora: " .. Silver(s.perHour) end
  end
  local perHour = ns.FarmLastHour and ns.FarmLastHour()
  if perHour then lines[#lines + 1] = "Última hora: " .. Silver(perHour) .. "/h" end
  local scans = PitiGoldsDB and PitiGoldsDB.scans or {}
  local last = scans[#scans]
  if last then
    lines[#lines + 1] = ("Por leer en el PC: %d escaneo%s"):format(#scans, #scans == 1 and "" or "s")
    lines[#lines + 1] = "Último: " .. Ago(last.time)
  end
  if statusText then
    statusText:SetText(table.concat(lines, "\n"))
    panel:SetHeight(30 + LINE_HEIGHT * #lines + 74)
  end
  if ahStatus then ahStatus:SetText(ns.Scan.Status() or "") end
  if ns.Session then ns.Session.Refresh() end
  if ns.Tracker then ns.Tracker.Refresh() end
end

-- Para las pruebas.
function ns.PanelText()
  return statusText and statusText:GetText() or ""
end

local function SavePosition(frame)
  local point, _, relativePoint, x, y = frame:GetPoint()
  PitiGoldsDB.ui.point = { point, relativePoint, x, y }
end

local function CreatePanel()
  panel = CreateFrame("Frame", "PitiGoldsPanel", UIParent, "BackdropTemplate")
  panel:SetSize(190, 142)
  local p = PitiGoldsDB.ui.point
  if p then
    panel:SetPoint(p[1], UIParent, p[2], p[3], p[4])
  else
    panel:SetPoint("TOPRIGHT", UIParent, "TOPRIGHT", -220, -200)
  end
  panel:SetMovable(true)
  panel:EnableMouse(true)
  panel:RegisterForDrag("LeftButton")
  panel:SetScript("OnDragStart", panel.StartMoving)
  panel:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    SavePosition(self)
  end)
  panel:SetBackdrop({
    bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    edgeSize = 12,
    insets = { left = 3, right = 3, top = 3, bottom = 3 },
  })
  panel:SetBackdropColor(0, 0, 0, 0.8)

  local title = panel:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  title:SetPoint("TOPLEFT", 8, -7)
  title:SetText("PitiGolds")

  statusText = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  statusText:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -3)
  statusText:SetJustifyH("LEFT")

  local best = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
  best:SetSize(174, 20)
  best:SetPoint("BOTTOM", 0, 50)
  best:SetText("Mejor farmeo")
  best:SetScript("OnClick", function() ns.Methods.Toggle() end)

  local session = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
  session:SetSize(174, 20)
  session:SetPoint("BOTTOM", 0, 28)
  session:SetText("Sesión")
  session:SetScript("OnClick", function() ns.Session.Toggle() end)

  local active = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
  active:SetSize(174, 20)
  active:SetPoint("BOTTOM", 0, 6)
  active:SetText("Farmeos activos")
  active:SetScript("OnClick", function() ns.Tracker.Toggle() end)

  if PitiGoldsDB.ui.hidden then panel:Hide() end
end

local function CreateAuctionBar()
  local parent = AuctionHouseFrame or UIParent
  ahBar = CreateFrame("Frame", nil, parent)
  ahBar:SetSize(520, 22)
  if AuctionHouseFrame then
    ahBar:SetPoint("BOTTOMLEFT", AuctionHouseFrame, "TOPLEFT", 60, 2)
  else
    ahBar:SetPoint("TOP", UIParent, "TOP", 0, -80)
  end

  local full = CreateFrame("Button", nil, ahBar, "UIPanelButtonTemplate")
  full:SetSize(120, 22)
  full:SetPoint("LEFT")
  full:SetText("PG: Completo")
  full:SetScript("OnClick", function() ns.Scan.StartFull() end)

  local mats = CreateFrame("Button", nil, ahBar, "UIPanelButtonTemplate")
  mats:SetSize(120, 22)
  mats:SetPoint("LEFT", full, "RIGHT", 4, 0)
  mats:SetText("PG: Materiales")
  mats:SetScript("OnClick", function() ns.Scan.StartMaterials() end)

  -- Cuántas veces quieres fabricar la receta del botón Buscar: al abrir uno de sus materiales
  -- se marca para comprar lo que pide multiplicado por esto (menos lo que ya tienes).
  local label = ahBar:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  label:SetPoint("LEFT", mats, "RIGHT", 10, 0)
  label:SetText("Fabricar x")
  local box = CreateFrame("EditBox", nil, ahBar, "InputBoxTemplate")
  box:SetSize(40, 20)
  box:SetPoint("LEFT", label, "RIGHT", 8, 0)
  box:SetAutoFocus(false)
  box:SetNumeric(true)
  box:SetMaxLetters(3)
  box:SetText(tostring(ns.craftCount or 1))
  local function Commit(self)
    ns.SetCraftCount(tonumber(self:GetText()) or 1)
    self:ClearFocus()
  end
  box:SetScript("OnEnterPressed", Commit)
  box:SetScript("OnEditFocusLost", function(self) ns.SetCraftCount(tonumber(self:GetText()) or 1) end)
  box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
  ns.craftCountBox = box

  ahStatus = ahBar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  ahStatus:SetPoint("LEFT", box, "RIGHT", 8, 0)
end

function ns.UpdateCraftCountBox()
  local box = ns.craftCountBox
  if box and tostring(ns.craftCount) ~= box:GetText() then box:SetText(tostring(ns.craftCount)) end
end

function ns.ShowAuctionButtons()
  if not ahBar then CreateAuctionBar() end
  ahBar:Show()
  ns.RefreshUI()
end

function ns.HideAuctionButtons()
  if ahBar then ahBar:Hide() end
end

local function RefreshLoop()
  ns.RefreshUI()
  C_Timer.After(CLOCK_SECONDS, RefreshLoop)
end

ns.On("PLAYER_LOGIN", function()
  CreatePanel()
  RefreshLoop()
end)

ns.Command("panel", "muestra u oculta el panel de PitiGolds", function()
  if panel:IsShown() then
    panel:Hide()
    PitiGoldsDB.ui.hidden = true
  else
    panel:Show()
    PitiGoldsDB.ui.hidden = nil
  end
end)
