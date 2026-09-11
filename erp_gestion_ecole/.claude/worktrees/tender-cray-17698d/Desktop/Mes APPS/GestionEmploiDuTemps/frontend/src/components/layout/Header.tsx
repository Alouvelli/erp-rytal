import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bars3Icon, SunIcon, MoonIcon, BellIcon,
  ArrowRightOnRectangleIcon, UserCircleIcon,
} from '@heroicons/react/24/outline';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';
import { notificationApi } from '../../services/api';
import { Notification } from '../../types';
import { Menu, Transition } from '@headlessui/react';
import { Fragment } from 'react';

export default function Header({ onMenuClick }: { onMenuClick: () => void }) {
  const { user, logout } = useAuth();
  const { dark, toggle } = useTheme();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showNotif, setShowNotif] = useState(false);

  useEffect(() => {
    if (user) notificationApi.getAll().then(({ data }) => setNotifications(data.data));
  }, [user]);

  const unread = notifications.filter(n => !n.isRead).length;

  const markAllRead = async () => {
    await notificationApi.markAllRead();
    setNotifications(prev => prev.map(n => ({ ...n, isRead: true })));
  };

  return (
    <header className="h-16 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between px-4 shrink-0 z-10">
      <div className="flex items-center gap-3">
        <button onClick={onMenuClick} className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
          <Bars3Icon className="w-5 h-5 text-gray-500" />
        </button>
        <div className="hidden sm:block">
          <p className="text-sm font-semibold text-gray-900 dark:text-white">
            {user ? `Bonjour, ${user.firstName} 👋` : 'Chargement...'}
          </p>
          <p className="text-xs text-gray-500">{new Date().toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })}</p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {/* Theme toggle */}
        <button onClick={toggle} className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
          {dark ? <SunIcon className="w-5 h-5 text-yellow-500" /> : <MoonIcon className="w-5 h-5 text-gray-500" />}
        </button>

        {/* Notifications */}
        <div className="relative">
          <button onClick={() => setShowNotif(!showNotif)} className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors relative">
            <BellIcon className="w-5 h-5 text-gray-500" />
            {unread > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-red-500 text-white text-xs rounded-full flex items-center justify-center">{unread}</span>
            )}
          </button>
          {showNotif && (
            <div className="absolute right-0 mt-2 w-80 card shadow-xl z-50 overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
                <p className="font-semibold text-sm">Notifications</p>
                {unread > 0 && <button onClick={markAllRead} className="text-xs text-primary-600 hover:underline">Tout marquer lu</button>}
              </div>
              <div className="max-h-72 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-800">
                {notifications.length === 0 && <p className="text-sm text-gray-500 text-center py-6">Aucune notification</p>}
                {notifications.slice(0, 10).map(n => (
                  <div key={n.id} className={`px-4 py-3 text-sm ${!n.isRead ? 'bg-blue-50 dark:bg-blue-900/10' : ''}`}>
                    <p className="font-medium text-gray-900 dark:text-white">{n.title}</p>
                    <p className="text-gray-500 text-xs mt-0.5">{n.message}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* User menu */}
        <Menu as="div" className="relative">
          <Menu.Button className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
            <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-white text-sm font-bold">
              {user?.firstName?.[0]}{user?.lastName?.[0]}
            </div>
          </Menu.Button>
          <Transition as={Fragment}
            enter="transition ease-out duration-100" enterFrom="opacity-0 scale-95" enterTo="opacity-100 scale-100"
            leave="transition ease-in duration-75" leaveFrom="opacity-100 scale-100" leaveTo="opacity-0 scale-95">
            <Menu.Items className="absolute right-0 mt-2 w-48 card shadow-xl py-1 z-50">
              <Menu.Item>
                {({ active }) => (
                  <button onClick={() => navigate('/profile')} className={`flex items-center gap-2 w-full px-4 py-2 text-sm ${active ? 'bg-gray-50 dark:bg-gray-800' : ''}`}>
                    <UserCircleIcon className="w-4 h-4" /> Mon profil
                  </button>
                )}
              </Menu.Item>
              <Menu.Item>
                {({ active }) => (
                  <button onClick={logout} className={`flex items-center gap-2 w-full px-4 py-2 text-sm text-red-600 ${active ? 'bg-red-50 dark:bg-red-900/10' : ''}`}>
                    <ArrowRightOnRectangleIcon className="w-4 h-4" /> Déconnexion
                  </button>
                )}
              </Menu.Item>
            </Menu.Items>
          </Transition>
        </Menu>
      </div>
    </header>
  );
}
