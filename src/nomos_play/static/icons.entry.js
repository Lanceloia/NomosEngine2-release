import {createElement, Plus, Minus, ArrowLeft, RotateCcw, Check, Coins, Diamond, Star, User, Users, X, Shield, Sword, Moon, Eye, FlaskConical, Flag, Crown, Pause, Play, FastForward} from "lucide";

const icons = {plus: Plus, minus: Minus, back: ArrowLeft, restart: RotateCcw, check: Check, coins: Coins, diamond: Diamond, star: Star, user:User, users:Users, x:X, shield:Shield, sword:Sword, moon:Moon, eye:Eye, flask:FlaskConical, flag:Flag, crown:Crown, pause:Pause, play:Play, "skip-forward":FastForward};
window.NomosIcon = name => createElement(icons[name] || Diamond, {width: 18, height: 18, "aria-hidden": "true"});
