-- Interfaz mínima: un panel movible con el botón Exportar y dos botones de
-- escaneo encima de la ventana de la subasta.
local ADDON, ns = ...

local panel, statusText
local ahBar, ahStatus

local function Ago(t)
  local minutes = math.floor((time() - t) / 60)
  if minutes < 1 then return "ahora" end
  if minutes < 60 then return ("hace %d min"):format(minutes) end
  return ("hace %d h"):format(math.floor(minutes / 60))
end

function ns.RefreshUI()
  local scans = PitiGoldsDB and PitiGoldsDB.scans or {}
  local last = scans[#scans]
  local lines = {}
  lines[#lines + 1] = ("Sin exportar: %d escaneo%s"):format(#scans, #scans == 1 and "" or "s")
  if last then lines[#lines + 1] = "Último: " .. Ago(last.time) end
  local perHour = ns.FarmLastHour and ns.FarmLastHour()
  if perHour then lines[#lines + 1] = "Farmeo: " .. ns.Money(perHour) .. "/h" end
  if statusText then statusText:SetText(table.concat(lines, "\n")) end
  if ahStatus then ahStatus:SetText(ns.Scan.Status() or "") end
end

local function SavePosition(frame)
  local point, _, relativePoint, x, y = frame:GetPoint()
  PitiGoldsDB.ui.point = { point, relativePoint, x, y }
end

local function CreatePanel()
  panel = CreateFrame("Frame", "PitiGoldsPanel", UIParent, "BackdropTemplate")
  panel:SetSize(170, 88)
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

  local export = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
  export:SetSize(154, 20)
  export:SetPoint("BOTTOM", 0, 6)
  export:SetText("Exportar")
  export:SetScript("OnClick", ns.Export)

  if PitiGoldsDB.ui.hidden then panel:Hide() end
end

local function CreateAuctionBar()
  local parent = AuctionHouseFrame or UIParent
  ahBar = CreateFrame("Frame", nil, parent)
  ahBar:SetSize(360, 22)
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

  ahStatus = ahBar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  ahStatus:SetPoint("LEFT", mats, "RIGHT", 8, 0)
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
  C_Timer.After(30, RefreshLoop)
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
