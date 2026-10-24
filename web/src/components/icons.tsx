// A single icon vocabulary: one 24-grid, 1.7 stroke, round caps, currentColor.
// Unicode glyphs (⌂ ▤ ✳ ↗) rendered differently on every platform, which made
// the shell look unpolished; these shapes are identical everywhere.
import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Icon({ size = 20, children, ...rest }: IconProps) {
  return <svg
    viewBox="0 0 24 24"
    width={size}
    height={size}
    fill="none"
    stroke="currentColor"
    strokeWidth={1.7}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
    {...rest}
  >{children}</svg>
}

export function IconHome(props: IconProps) {
  return <Icon {...props}><path d="M4 10.4 12 4l8 6.4V19a1.6 1.6 0 0 1-1.6 1.6H5.6A1.6 1.6 0 0 1 4 19Z" /><path d="M9.6 20.6v-6.2h4.8v6.2" /></Icon>
}

export function IconLibrary(props: IconProps) {
  return <Icon {...props}><path d="M4 5.2h5.4v14.6H4zM14.6 5.2H20v14.6h-5.4z" /><path d="M9.4 8.6h5.2M9.4 12h5.2M9.4 15.4h5.2" /></Icon>
}

export function IconArrowUpRight(props: IconProps) {
  return <Icon {...props}><path d="M7.6 16.4 16.4 7.6M9.4 7.6h7v7" /></Icon>
}

export function IconArrowRight(props: IconProps) {
  return <Icon {...props}><path d="M4.8 12h14.4M13.6 6.4 19.2 12l-5.6 5.6" /></Icon>
}

export function IconChevronLeft(props: IconProps) {
  return <Icon {...props}><path d="M14.4 6.4 8.8 12l5.6 5.6" /></Icon>
}

export function IconChevronRight(props: IconProps) {
  return <Icon {...props}><path d="M9.6 6.4 15.2 12l-5.6 5.6" /></Icon>
}

export function IconChevronDown(props: IconProps) {
  return <Icon {...props}><path d="M6.4 9.6 12 15.2l5.6-5.6" /></Icon>
}

export function IconSidebar(props: IconProps) {
  return <Icon {...props}><rect x="3.4" y="4.6" width="17.2" height="14.8" rx="2.2" /><path d="M9.6 4.6v14.8" /></Icon>
}

export function IconSpark(props: IconProps) {
  return <Icon {...props}><path d="M12 3.6v4.2M12 16.2v4.2M4.6 12h4.2M15.2 12h4.2" /><path d="m7.2 7.2 2.4 2.4M14.4 14.4l2.4 2.4M16.8 7.2l-2.4 2.4M9.6 14.4l-2.4 2.4" /></Icon>
}

export function IconBoard(props: IconProps) {
  return <Icon {...props}><rect x="3.4" y="4" width="17.2" height="11.6" rx="1.8" /><path d="M12 15.6v4.4M8.4 20h7.2" /></Icon>
}

export function IconCheck(props: IconProps) {
  return <Icon {...props}><path d="m5.2 12.6 4.4 4.4L18.8 7.6" /></Icon>
}

export function IconPlus(props: IconProps) {
  return <Icon {...props}><path d="M12 5.2v13.6M5.2 12h13.6" /></Icon>
}

export function IconCheckCircle(props: IconProps) {
  return <Icon {...props}><circle cx="12" cy="12" r="8.4" /><path d="m8.4 12.2 2.6 2.6 4.6-5.2" /></Icon>
}

export function IconClock(props: IconProps) {
  return <Icon {...props}><circle cx="12" cy="12" r="8.4" /><path d="M12 7.4V12l3.2 2" /></Icon>
}

export function IconLock(props: IconProps) {
  return <Icon {...props}><rect x="5" y="10.4" width="14" height="9.4" rx="2" /><path d="M8.4 10.4V8.2a3.6 3.6 0 0 1 7.2 0v2.2" /></Icon>
}

export function IconBook(props: IconProps) {
  return <Icon {...props}><path d="M4.4 5.2A1.6 1.6 0 0 1 6 3.6h4.6A2.4 2.4 0 0 1 13 6v14a2 2 0 0 0-2-2H4.4Z" /><path d="M19.6 5.2A1.6 1.6 0 0 0 18 3.6h-4.6A2.4 2.4 0 0 0 11 6v14a2 2 0 0 1 2-2h6.6Z" /></Icon>
}

export function IconExam(props: IconProps) {
  return <Icon {...props}><path d="M14.4 3.6H7a1.8 1.8 0 0 0-1.8 1.8v13.2A1.8 1.8 0 0 0 7 20.4h10a1.8 1.8 0 0 0 1.8-1.8V8Z" /><path d="M14.2 3.8V8h4.4" /><path d="m8.8 13.6 1.8 1.8 3.4-3.8" /></Icon>
}

export function IconRoute(props: IconProps) {
  return <Icon {...props}><circle cx="6.4" cy="18.4" r="2.4" /><circle cx="17.6" cy="5.6" r="2.4" /><path d="M17.6 8v3.2a4 4 0 0 1-4 4H8.4a2 2 0 0 0-2 2v1.2" /></Icon>
}

export function IconSearch(props: IconProps) {
  return <Icon {...props}><circle cx="11" cy="11" r="6.4" /><path d="m15.8 15.8 4 4" /></Icon>
}

export function IconSend(props: IconProps) {
  return <Icon {...props}><path d="M20.4 3.6 10.6 13.4M20.4 3.6l-6.2 16.8-3.6-7-7-3.6Z" /></Icon>
}

export function IconRefresh(props: IconProps) {
  return <Icon {...props}><path d="M20 12a8 8 0 1 1-2.6-5.9" /><path d="M20.2 4.2v4.4h-4.4" /></Icon>
}

export function IconAlert(props: IconProps) {
  return <Icon {...props}><path d="M12 4.2 3.6 19.2h16.8Z" /><path d="M12 9.6v4M12 16.4v.4" /></Icon>
}

export function IconNote(props: IconProps) {
  return <Icon {...props}><path d="M5.2 4.6h9.6l4 4v10.8a1.6 1.6 0 0 1-1.6 1.6H5.2Z" /><path d="M14.4 4.8v4.2h4.2M8.4 13h7.2M8.4 16.4h4.8" /></Icon>
}

export function IconSun(props: IconProps) {
  return <Icon {...props}><circle cx="12" cy="12" r="4.2" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7" /></Icon>
}

export function IconMoon(props: IconProps) {
  return <Icon {...props}><path d="M20 14.4A8.4 8.4 0 0 1 9.6 4 8.4 8.4 0 1 0 20 14.4Z" /></Icon>
}

export function IconGlobe(props: IconProps) {
  return <Icon {...props}><circle cx="12" cy="12" r="8.4" /><path d="M3.8 12h16.4M12 3.6c2.4 2.6 3.6 5.4 3.6 8.4s-1.2 5.8-3.6 8.4c-2.4-2.6-3.6-5.4-3.6-8.4S9.6 6.2 12 3.6Z" /></Icon>
}

// Result stars keep their shape at every size; the ★/☆ pair changed weight
// and spacing between platforms and could not be filled consistently.
export function IconStar({ filled = false, ...props }: IconProps & { filled?: boolean }) {
  return <Icon {...props} fill={filled ? 'currentColor' : 'none'} strokeWidth={filled ? 0 : 1.5}>
    <path d="M12 3.8l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8z" />
  </Icon>
}
