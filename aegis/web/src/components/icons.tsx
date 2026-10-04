// Icon set for the Aegis dashboard: Phosphor icons behind the lucide-style names the codebase already uses.
// Owner: ICONS (UI fleet). Add new names here (mapped to a Phosphor icon) rather than importing lucide-react.
import { forwardRef, type ForwardRefExoticComponent, type RefAttributes } from 'react';
import {
  ArrowCounterClockwise as PhArrowCounterClockwise,
  ArrowDown as PhArrowDown,
  ArrowDownLeft as PhArrowDownLeft,
  ArrowLeft as PhArrowLeft,
  ArrowRight as PhArrowRight,
  ArrowSquareOut as PhArrowSquareOut,
  ArrowUUpLeft as PhArrowUUpLeft,
  ArrowUp as PhArrowUp,
  ArrowUpRight as PhArrowUpRight,
  ArrowsClockwise as PhArrowsClockwise,
  ArrowsLeftRight as PhArrowsLeftRight,
  ArrowsOut as PhArrowsOut,
  Broadcast as PhBroadcast,
  Bug as PhBug,
  Building as PhBuilding,
  BuildingOffice as PhBuildingOffice,
  CaretDown as PhCaretDown,
  CaretRight as PhCaretRight,
  CaretUp as PhCaretUp,
  CaretUpDown as PhCaretUpDown,
  ChartBar as PhChartBar,
  ChartLine as PhChartLine,
  ChatCenteredText as PhChatCenteredText,
  Check as PhCheck,
  CheckCircle as PhCheckCircle,
  Checks as PhChecks,
  Circle as PhCircle,
  CircleDashed as PhCircleDashed,
  CircleNotch as PhCircleNotch,
  Clipboard as PhClipboard,
  Clock as PhClock,
  ClockCounterClockwise as PhClockCounterClockwise,
  Cloud as PhCloud,
  CloudSlash as PhCloudSlash,
  Code as PhCode,
  Columns as PhColumns,
  Copy as PhCopy,
  Cpu as PhCpu,
  CreditCard as PhCreditCard,
  Crosshair as PhCrosshair,
  Crown as PhCrown,
  CursorClick as PhCursorClick,
  Database as PhDatabase,
  DownloadSimple as PhDownloadSimple,
  Eye as PhEye,
  EyeSlash as PhEyeSlash,
  FileArrowDown as PhFileArrowDown,
  FileCode as PhFileCode,
  FileLock as PhFileLock,
  FileText as PhFileText,
  Flask as PhFlask,
  FloppyDisk as PhFloppyDisk,
  FlowArrow as PhFlowArrow,
  Funnel as PhFunnel,
  Gauge as PhGauge,
  GearSix as PhGearSix,
  GitCommit as PhGitCommit,
  GitDiff as PhGitDiff,
  Globe as PhGlobe,
  HardDrive as PhHardDrive,
  HardDrives as PhHardDrives,
  Hash as PhHash,
  Heartbeat as PhHeartbeat,
  HourglassMedium as PhHourglassMedium,
  IdentificationCard as PhIdentificationCard,
  Info as PhInfo,
  Key as PhKey,
  Laptop as PhLaptop,
  Lightning as PhLightning,
  Link as PhLink,
  LinkSimple as PhLinkSimple,
  Lock as PhLock,
  LockOpen as PhLockOpen,
  MagnifyingGlass as PhMagnifyingGlass,
  MapPin as PhMapPin,
  Minus as PhMinus,
  Package as PhPackage,
  PaperPlaneTilt as PhPaperPlaneTilt,
  Path as PhPath,
  Pause as PhPause,
  Percent as PhPercent,
  PiggyBank as PhPiggyBank,
  Play as PhPlay,
  Plug as PhPlug,
  Plus as PhPlus,
  Power as PhPower,
  Printer as PhPrinter,
  Prohibit as PhProhibit,
  Pulse as PhPulse,
  PushPin as PhPushPin,
  Robot as PhRobot,
  Rocket as PhRocket,
  Rows as PhRows,
  Scales as PhScales,
  Scroll as PhScroll,
  Shield as PhShield,
  ShieldCheck as PhShieldCheck,
  ShieldCheckered as PhShieldCheckered,
  ShieldPlus as PhShieldPlus,
  ShieldSlash as PhShieldSlash,
  ShieldWarning as PhShieldWarning,
  SidebarSimple as PhSidebarSimple,
  SkipForward as PhSkipForward,
  SlidersHorizontal as PhSlidersHorizontal,
  Stack as PhStack,
  Syringe as PhSyringe,
  Terminal as PhTerminal,
  TerminalWindow as PhTerminalWindow,
  Timer as PhTimer,
  ToggleLeft as PhToggleLeft,
  Trash as PhTrash,
  Tray as PhTray,
  TrendDown as PhTrendDown,
  TrendUp as PhTrendUp,
  User as PhUser,
  UserCheck as PhUserCheck,
  Users as PhUsers,
  Wallet as PhWallet,
  Warning as PhWarning,
  WarningCircle as PhWarningCircle,
  WarningOctagon as PhWarningOctagon,
  WifiSlash as PhWifiSlash,
  Wrench as PhWrench,
  ArrowDownRight as PhArrowDownRight,
  Fingerprint as PhFingerprint,
  GitMerge as PhGitMerge,
  RadioButton as PhRadioButton,
  SignIn as PhSignIn,
  X as PhX,
  XCircle as PhXCircle,
  type Icon as PhosphorIcon,
  type IconProps as PhosphorIconProps,
} from '@phosphor-icons/react';

export interface IconProps extends Omit<PhosphorIconProps, 'ref'> {
  /** lucide compatibility: >= 2.2 renders the bold weight, otherwise ignored. */
  strokeWidth?: number | string;
  /** lucide compatibility: ignored. */
  absoluteStrokeWidth?: boolean;
}
export type LucideProps = IconProps;
export type LucideIcon = ForwardRefExoticComponent<IconProps & RefAttributes<SVGSVGElement>>;

function wrap(Ph: PhosphorIcon, name: string): LucideIcon {
  const C = forwardRef<SVGSVGElement, IconProps>(({ strokeWidth, absoluteStrokeWidth: _abs, weight, size, ...rest }, ref) => {
    void _abs;
    const w = weight ?? (strokeWidth != null && Number(strokeWidth) >= 2.2 ? 'bold' : 'regular');
    // size defaults to 1em; Tailwind size-*/h-*/w-* classes (CSS) override the width/height attributes.
    return <Ph ref={ref} size={size ?? '1em'} weight={w} aria-hidden={rest['aria-label'] ? undefined : true} focusable="false" {...rest} />;
  });
  C.displayName = name;
  return C;
}

export const Activity = wrap(PhPulse, 'Activity');
export const AlertOctagon = wrap(PhWarningOctagon, 'AlertOctagon');
export const AlertTriangle = wrap(PhWarning, 'AlertTriangle');
export const ArrowDown = wrap(PhArrowDown, 'ArrowDown');
export const ArrowDownLeft = wrap(PhArrowDownLeft, 'ArrowDownLeft');
export const ArrowLeft = wrap(PhArrowLeft, 'ArrowLeft');
export const ArrowLeftRight = wrap(PhArrowsLeftRight, 'ArrowLeftRight');
export const ArrowRight = wrap(PhArrowRight, 'ArrowRight');
export const ArrowUp = wrap(PhArrowUp, 'ArrowUp');
export const ArrowUpRight = wrap(PhArrowUpRight, 'ArrowUpRight');
export const Ban = wrap(PhProhibit, 'Ban');
export const Bomb = wrap(PhBug, 'Bomb');
export const Bot = wrap(PhRobot, 'Bot');
export const Building = wrap(PhBuilding, 'Building');
export const Building2 = wrap(PhBuildingOffice, 'Building2');
export const ChartBar = wrap(PhChartBar, 'ChartBar');
export const ChartNoAxesColumn = wrap(PhChartBar, 'ChartNoAxesColumn');
export const Check = wrap(PhCheck, 'Check');
export const CheckCheck = wrap(PhChecks, 'CheckCheck');
export const CheckCircle2 = wrap(PhCheckCircle, 'CheckCircle2');
export const CheckIcon = wrap(PhCheck, 'CheckIcon');
export const ChevronDown = wrap(PhCaretDown, 'ChevronDown');
export const ChevronDownIcon = wrap(PhCaretDown, 'ChevronDownIcon');
export const ChevronRight = wrap(PhCaretRight, 'ChevronRight');
export const ChevronRightIcon = wrap(PhCaretRight, 'ChevronRightIcon');
export const ChevronUpIcon = wrap(PhCaretUp, 'ChevronUpIcon');
export const ChevronsUpDown = wrap(PhCaretUpDown, 'ChevronsUpDown');
export const Circle = wrap(PhCircle, 'Circle');
export const CircleAlert = wrap(PhWarningCircle, 'CircleAlert');
export const CircleCheck = wrap(PhCheckCircle, 'CircleCheck');
export const CircleCheckIcon = wrap(PhCheckCircle, 'CircleCheckIcon');
export const CircleDashed = wrap(PhCircleDashed, 'CircleDashed');
export const ClipboardCopy = wrap(PhClipboard, 'ClipboardCopy');
export const Clock = wrap(PhClock, 'Clock');
export const Cloud = wrap(PhCloud, 'Cloud');
export const CloudOff = wrap(PhCloudSlash, 'CloudOff');
export const Code2 = wrap(PhCode, 'Code2');
export const Columns2 = wrap(PhColumns, 'Columns2');
export const Copy = wrap(PhCopy, 'Copy');
export const Cpu = wrap(PhCpu, 'Cpu');
export const CreditCard = wrap(PhCreditCard, 'CreditCard');
export const Crown = wrap(PhCrown, 'Crown');
export const Database = wrap(PhDatabase, 'Database');
export const DatabaseZap = wrap(PhDatabase, 'DatabaseZap');
export const Diff = wrap(PhGitDiff, 'Diff');
export const Download = wrap(PhDownloadSimple, 'Download');
export const Expand = wrap(PhArrowsOut, 'Expand');
export const ExternalLink = wrap(PhArrowSquareOut, 'ExternalLink');
export const Eye = wrap(PhEye, 'Eye');
export const EyeOff = wrap(PhEyeSlash, 'EyeOff');
export const FileBarChart = wrap(PhFileText, 'FileBarChart');
export const FileCode = wrap(PhFileCode, 'FileCode');
export const FileDiff = wrap(PhGitDiff, 'FileDiff');
export const FileInput = wrap(PhFileArrowDown, 'FileInput');
export const FileLock = wrap(PhFileLock, 'FileLock');
export const FlaskConical = wrap(PhFlask, 'FlaskConical');
export const Gauge = wrap(PhGauge, 'Gauge');
export const GitCommitHorizontal = wrap(PhGitCommit, 'GitCommitHorizontal');
export const GitCompare = wrap(PhGitDiff, 'GitCompare');
export const GitCompareArrows = wrap(PhGitDiff, 'GitCompareArrows');
export const Globe = wrap(PhGlobe, 'Globe');
export const HardDrive = wrap(PhHardDrive, 'HardDrive');
export const Hash = wrap(PhHash, 'Hash');
export const HeartPulse = wrap(PhHeartbeat, 'HeartPulse');
export const History = wrap(PhClockCounterClockwise, 'History');
export const IdCard = wrap(PhIdentificationCard, 'IdCard');
export const Inbox = wrap(PhTray, 'Inbox');
export const Info = wrap(PhInfo, 'Info');
export const InfoIcon = wrap(PhInfo, 'InfoIcon');
export const KeyRound = wrap(PhKey, 'KeyRound');
export const Laptop = wrap(PhLaptop, 'Laptop');
export const LineChart = wrap(PhChartLine, 'LineChart');
export const Link = wrap(PhLink, 'Link');
export const Link2 = wrap(PhLinkSimple, 'Link2');
export const ListFilter = wrap(PhFunnel, 'ListFilter');
export const Loader2 = wrap(PhCircleNotch, 'Loader2');
export const Loader2Icon = wrap(PhCircleNotch, 'Loader2Icon');
export const LoaderCircle = wrap(PhCircleNotch, 'LoaderCircle');
export const Lock = wrap(PhLock, 'Lock');
export const LockOpen = wrap(PhLockOpen, 'LockOpen');
export const MapPinOff = wrap(PhMapPin, 'MapPinOff');
export const MessageSquare = wrap(PhChatCenteredText, 'MessageSquare');
export const Minus = wrap(PhMinus, 'Minus');
export const OctagonXIcon = wrap(PhWarningOctagon, 'OctagonXIcon');
export const Package = wrap(PhPackage, 'Package');
export const PanelLeftClose = wrap(PhSidebarSimple, 'PanelLeftClose');
export const PanelLeftOpen = wrap(PhSidebarSimple, 'PanelLeftOpen');
export const ParkingSquare = wrap(PhHourglassMedium, 'ParkingSquare');
export const Pause = wrap(PhPause, 'Pause');
export const Percent = wrap(PhPercent, 'Percent');
export const PiggyBank = wrap(PhPiggyBank, 'PiggyBank');
export const Pin = wrap(PhPushPin, 'Pin');
export const Play = wrap(PhPlay, 'Play');
export const Plug = wrap(PhPlug, 'Plug');
export const Plus = wrap(PhPlus, 'Plus');
export const Power = wrap(PhPower, 'Power');
export const PowerOff = wrap(PhPower, 'PowerOff');
export const Printer = wrap(PhPrinter, 'Printer');
export const Radar = wrap(PhCrosshair, 'Radar');
export const Radio = wrap(PhBroadcast, 'Radio');
export const RefreshCw = wrap(PhArrowsClockwise, 'RefreshCw');
export const Rocket = wrap(PhRocket, 'Rocket');
export const RotateCcw = wrap(PhArrowCounterClockwise, 'RotateCcw');
export const Route = wrap(PhPath, 'Route');
export const Rows2 = wrap(PhRows, 'Rows2');
export const Save = wrap(PhFloppyDisk, 'Save');
export const Scale = wrap(PhScales, 'Scale');
export const ScanSearch = wrap(PhMagnifyingGlass, 'ScanSearch');
export const ScrollText = wrap(PhScroll, 'ScrollText');
export const Search = wrap(PhMagnifyingGlass, 'Search');
export const SearchIcon = wrap(PhMagnifyingGlass, 'SearchIcon');
export const SearchX = wrap(PhMagnifyingGlass, 'SearchX');
export const Send = wrap(PhPaperPlaneTilt, 'Send');
export const Server = wrap(PhHardDrives, 'Server');
export const Settings2 = wrap(PhGearSix, 'Settings2');
export const Shield = wrap(PhShield, 'Shield');
export const ShieldAlert = wrap(PhShieldWarning, 'ShieldAlert');
export const ShieldBan = wrap(PhShieldSlash, 'ShieldBan');
export const ShieldCheck = wrap(PhShieldCheck, 'ShieldCheck');
export const ShieldHalf = wrap(PhShieldCheckered, 'ShieldHalf');
export const ShieldMinus = wrap(PhShieldSlash, 'ShieldMinus');
export const ShieldOff = wrap(PhShieldSlash, 'ShieldOff');
export const ShieldPlus = wrap(PhShieldPlus, 'ShieldPlus');
export const ShieldQuestionMark = wrap(PhShield, 'ShieldQuestionMark');
export const ShieldX = wrap(PhShieldWarning, 'ShieldX');
export const SkipForward = wrap(PhSkipForward, 'SkipForward');
export const SlidersHorizontal = wrap(PhSlidersHorizontal, 'SlidersHorizontal');
export const Sparkles = wrap(PhStack, 'Sparkles');
export const SquareTerminal = wrap(PhTerminalWindow, 'SquareTerminal');
export const Syringe = wrap(PhSyringe, 'Syringe');
export const Terminal = wrap(PhTerminal, 'Terminal');
export const TerminalSquare = wrap(PhTerminalWindow, 'TerminalSquare');
export const Timer = wrap(PhTimer, 'Timer');
export const ToggleLeft = wrap(PhToggleLeft, 'ToggleLeft');
export const Trash2 = wrap(PhTrash, 'Trash2');
export const TrendingDown = wrap(PhTrendDown, 'TrendingDown');
export const TrendingUp = wrap(PhTrendUp, 'TrendingUp');
export const TriangleAlert = wrap(PhWarning, 'TriangleAlert');
export const TriangleAlertIcon = wrap(PhWarning, 'TriangleAlertIcon');
export const Undo2 = wrap(PhArrowUUpLeft, 'Undo2');
export const User = wrap(PhUser, 'User');
export const UserCheck = wrap(PhUserCheck, 'UserCheck');
export const Users = wrap(PhUsers, 'Users');
export const View = wrap(PhEye, 'View');
export const Wallet = wrap(PhWallet, 'Wallet');
export const Wand2 = wrap(PhCursorClick, 'Wand2');
export const WifiOff = wrap(PhWifiSlash, 'WifiOff');
export const Workflow = wrap(PhFlowArrow, 'Workflow');
export const Wrench = wrap(PhWrench, 'Wrench');
export const ArrowDownRight = wrap(PhArrowDownRight, 'ArrowDownRight');
export const CircleDot = wrap(PhRadioButton, 'CircleDot');
export const Fingerprint = wrap(PhFingerprint, 'Fingerprint');
export const GitMerge = wrap(PhGitMerge, 'GitMerge');
export const LogIn = wrap(PhSignIn, 'LogIn');
export const X = wrap(PhX, 'X');
export const XCircle = wrap(PhXCircle, 'XCircle');
export const XIcon = wrap(PhX, 'XIcon');
export const Zap = wrap(PhLightning, 'Zap');

/** Name -> icon lookup for string icon names (PageMeta.icon, colour/format tables). */
export const icons: Record<string, LucideIcon> = {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowDown,
  ArrowDownLeft,
  ArrowLeft,
  ArrowLeftRight,
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Ban,
  Bomb,
  Bot,
  Building,
  Building2,
  ChartBar,
  ChartNoAxesColumn,
  Check,
  CheckCheck,
  CheckCircle2,
  CheckIcon,
  ChevronDown,
  ChevronDownIcon,
  ChevronRight,
  ChevronRightIcon,
  ChevronUpIcon,
  ChevronsUpDown,
  Circle,
  CircleAlert,
  CircleCheck,
  CircleCheckIcon,
  CircleDashed,
  ClipboardCopy,
  Clock,
  Cloud,
  CloudOff,
  Code2,
  Columns2,
  Copy,
  Cpu,
  CreditCard,
  Crown,
  Database,
  DatabaseZap,
  Diff,
  Download,
  Expand,
  ExternalLink,
  Eye,
  EyeOff,
  FileBarChart,
  FileCode,
  FileDiff,
  FileInput,
  FileLock,
  FlaskConical,
  Gauge,
  GitCommitHorizontal,
  GitCompare,
  GitCompareArrows,
  Globe,
  HardDrive,
  Hash,
  HeartPulse,
  History,
  IdCard,
  Inbox,
  Info,
  InfoIcon,
  KeyRound,
  Laptop,
  LineChart,
  Link,
  Link2,
  ListFilter,
  Loader2,
  Loader2Icon,
  LoaderCircle,
  Lock,
  LockOpen,
  MapPinOff,
  MessageSquare,
  Minus,
  OctagonXIcon,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  ParkingSquare,
  Pause,
  Percent,
  PiggyBank,
  Pin,
  Play,
  Plug,
  Plus,
  Power,
  PowerOff,
  Printer,
  Radar,
  Radio,
  RefreshCw,
  Rocket,
  RotateCcw,
  Route,
  Rows2,
  Save,
  Scale,
  ScanSearch,
  ScrollText,
  Search,
  SearchIcon,
  SearchX,
  Send,
  Server,
  Settings2,
  Shield,
  ShieldAlert,
  ShieldBan,
  ShieldCheck,
  ShieldHalf,
  ShieldMinus,
  ShieldOff,
  ShieldPlus,
  ShieldQuestionMark,
  ShieldX,
  SkipForward,
  SlidersHorizontal,
  Sparkles,
  SquareTerminal,
  Syringe,
  Terminal,
  TerminalSquare,
  Timer,
  ToggleLeft,
  Trash2,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  TriangleAlertIcon,
  Undo2,
  User,
  UserCheck,
  Users,
  View,
  Wallet,
  Wand2,
  WifiOff,
  Workflow,
  Wrench,
  ArrowDownRight,
  CircleDot,
  Fingerprint,
  GitMerge,
  LogIn,
  X,
  XCircle,
  XIcon,
  Zap,
};
