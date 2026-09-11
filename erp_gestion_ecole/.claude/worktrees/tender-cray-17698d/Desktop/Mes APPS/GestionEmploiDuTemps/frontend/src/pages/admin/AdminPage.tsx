import { useState } from 'react';
import UsersTab from './UsersTab';
import ClassesTab from './ClassesTab';
import SubjectsTab from './SubjectsTab';
import RoomsTab from './RoomsTab';

const TABS = [
  { id: 'users', label: 'Utilisateurs' },
  { id: 'classes', label: 'Classes' },
  { id: 'subjects', label: 'Matières' },
  { id: 'rooms', label: 'Salles' },
];

export default function AdminPage() {
  const [tab, setTab] = useState('users');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Administration</h1>
        <p className="text-sm text-gray-500 mt-1">Gestion des ressources académiques</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-800">
        <nav className="flex gap-1 -mb-px">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-primary-600 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              }`}>
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      <div>
        {tab === 'users' && <UsersTab />}
        {tab === 'classes' && <ClassesTab />}
        {tab === 'subjects' && <SubjectsTab />}
        {tab === 'rooms' && <RoomsTab />}
      </div>
    </div>
  );
}
