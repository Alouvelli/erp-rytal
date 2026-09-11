import { NavLink } from 'react-router-dom';
import {
  HomeIcon, CalendarIcon, ClipboardDocumentCheckIcon,
  AcademicCapIcon, UserMinusIcon, XCircleIcon,
  Cog6ToothIcon, ChevronLeftIcon,
} from '@heroicons/react/24/outline';
import { useAuth } from '../../context/AuthContext';
import clsx from 'clsx';

interface NavItem { label: string; to: string; icon: React.ComponentType<any>; roles?: string[]; }

const NAV: NavItem[] = [
  { label: 'Tableau de bord', to: '/dashboard', icon: HomeIcon },
  { label: 'Emploi du temps', to: '/timetable', icon: CalendarIcon },
  { label: 'Émargements', to: '/attendance', icon: ClipboardDocumentCheckIcon },
  { label: 'Notes', to: '/grades', icon: AcademicCapIcon },
  { label: 'Absences', to: '/absences', icon: UserMinusIcon },
  { label: 'Annulations', to: '/cancellations', icon: XCircleIcon },
  { label: 'Administration', to: '/admin', icon: Cog6ToothIcon, roles: ['ADMIN', 'SCOLARITE'] },
];

interface Props { open: boolean; onClose: () => void; }

export default function Sidebar({ open, onClose }: Props) {
  const { user } = useAuth();

  return (
    <>
      {/* Overlay mobile */}
      {open && <div className="fixed inset-0 z-20 bg-black/40 lg:hidden" onClick={onClose} />}

      <aside className={clsx(
        'fixed lg:relative z-30 h-full flex flex-col bg-gray-900 dark:bg-gray-950 text-white transition-all duration-300',
        open ? 'w-64' : 'w-0 lg:w-16 overflow-hidden'
      )}>
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 h-16 border-b border-gray-800 shrink-0">
          <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center shrink-0">
            <AcademicCapIcon className="w-5 h-5" />
          </div>
          {open && <span className="font-bold text-lg truncate">GestionEDT</span>}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 space-y-1 px-2 overflow-y-auto">
          {NAV.filter(item => !item.roles || item.roles.includes(user?.role || '')).map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors group',
                isActive
                  ? 'bg-primary-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              )}
            >
              <item.icon className="w-5 h-5 shrink-0" />
              {open && <span className="truncate">{item.label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* User info */}
        {open && user && (
          <div className="px-4 py-3 border-t border-gray-800 shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-sm font-bold shrink-0">
                {user.firstName[0]}{user.lastName[0]}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">{user.firstName} {user.lastName}</p>
                <p className="text-xs text-gray-400 truncate">{user.role}</p>
              </div>
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
