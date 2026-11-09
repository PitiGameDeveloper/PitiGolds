-- Instructores: al abrir su ventana se apunta qué enseñan, a qué nivel de profesión y de
-- personaje, y por cuánto. Es el único sitio donde Forever dice a qué nivel se aprende una
-- receta de instructor. Solo se ve lo que enseña el instructor que has podido abrir.
local ADDON, ns = ...

local FILTERS = { "available", "unavailable" }

-- Lo que no puedes aprender todavía es justo lo que interesa: se enseña mientras se lee y
-- luego se dejan los filtros de la ventana como estaban.
local function ShowEverything()
  local changed = {}
  if not (GetTrainerServiceTypeFilter and SetTrainerServiceTypeFilter) then return changed end
  for _, kind in ipairs(FILTERS) do
    if not GetTrainerServiceTypeFilter(kind) and pcall(SetTrainerServiceTypeFilter, kind, 1) then
      changed[#changed + 1] = kind
    end
  end
  return changed
end

local function Restore(changed)
  for _, kind in ipairs(changed) do pcall(SetTrainerServiceTypeFilter, kind, 0) end
end

local function ReadServices()
  local services, skills = {}, {}
  for i = 1, GetNumTrainerServices() or 0 do
    local name, _, kind = GetTrainerServiceInfo(i)
    if name and kind ~= "header" then
      local skill, rank
      if GetTrainerServiceSkillReq then skill, rank = GetTrainerServiceSkillReq(i) end
      if type(skill) == "string" and skill ~= "" then skills[skill] = (skills[skill] or 0) + 1 else skill = nil end
      services[#services + 1] = {
        name = name, skill = skill, rank = type(rank) == "number" and rank or 0,
        level = GetTrainerServiceLevelReq and GetTrainerServiceLevelReq(i) or nil,
        cost = GetTrainerServiceCost and GetTrainerServiceCost(i) or nil,
      }
    end
  end
  return services, skills
end

local function ScanTrainer()
  if not (GetNumTrainerServices and GetTrainerServiceInfo) then return end
  local changed = ShowEverything()
  local ok, services, skills = pcall(ReadServices)
  Restore(changed)
  if not ok then
    ns.Log("Instructor: no se ha podido leer: " .. tostring(services))
    return
  end

  -- Lo que no pide nivel de profesión no dice de cuál es: será de la que enseña este instructor.
  local main, most = nil, 0
  for skill, n in pairs(skills) do
    if n > most then main, most = skill, n end
  end
  if not main then return end

  local db = PitiGoldsDB
  db.trainerRecipes = db.trainerRecipes or {}
  local count = 0
  for _, s in ipairs(services) do
    local skill = s.skill or main
    db.trainerRecipes[skill] = db.trainerRecipes[skill] or {}
    db.trainerRecipes[skill][s.name] = { rank = s.rank, level = s.level, cost = s.cost, time = time() }
    count = count + 1
  end
  ns.Print(("Instructor de %s: %d recetas apuntadas."):format(main, count))
end

local function IsTrainerInteraction(kind)
  local P = Enum and Enum.PlayerInteractionType
  return P ~= nil and P.Trainer ~= nil and kind == P.Trainer
end

ns.On("TRAINER_SHOW", function() ns.Debounce("trainer", 0.5, ScanTrainer) end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", function(_, kind)
  if IsTrainerInteraction(kind) then ns.Debounce("trainer", 0.5, ScanTrainer) end
end)
